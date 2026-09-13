"""LanceDeck — start the helper, open the page, sit in the system tray.

No console: a small icon in the tray with Open, Setup, Calibrate and Quit.  Errors go to
lancedeck.log next to the app.  Started twice, the second launch just opens the page.
"""
import json
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tracker.paths import CFG_PATH, CFG_DEFAULT, ROOT, APP, VERSION, ensure_dirs


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def open_page(url: str) -> None:
    """The default browser on the page: Windows' own shell open first, Python's fallback second."""
    try:
        os.startfile(url)
        return
    except Exception:
        pass
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print("could not open a browser; open", url, "yourself")


def _icon_image():
    """The tray icon: an amber L on a dark hex, drawn here so no file is needed."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(32, 2), (60, 17), (60, 47), (32, 62), (4, 47), (4, 17)], fill=(14, 19, 26, 255), outline=(255, 179, 71, 255), width=3)
    d.rectangle([20, 16, 29, 48], fill=(255, 179, 71, 255))
    d.rectangle([20, 40, 46, 48], fill=(255, 179, 71, 255))
    return im


def main():
    ensure_dirs()
    if not os.path.exists(CFG_PATH):
        shutil.copyfile(CFG_DEFAULT, CFG_PATH)
    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    port = int(cfg.get("port", 8765))
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://localhost:{port}/"
    console = "--console" in sys.argv or not getattr(sys, "frozen", False) and "--tray" not in sys.argv

    if _port_in_use(port):                                  # already running: just show the page
        if "--no-browser" not in sys.argv:
            open_page(url)
        return

    if not console:                                          # windowed build: keep a log instead of a console
        log = open(os.path.join(ROOT, "lancedeck.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    print(f"{APP} {VERSION} — {url}")

    import uvicorn
    from tracker.server import app
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    if "--no-browser" not in sys.argv:
        def when_up():
            # the browser opens once the server answers — a fixed delay opened it on a
            # "cannot connect" page while the reader was still loading on slower PCs
            for _ in range(600):
                if _port_in_use(port):
                    break
                time.sleep(0.25)
            open_page(url)
        threading.Thread(target=when_up, daemon=True).start()

    import tracker.server as srv
    if console:
        srv.quit_hook = lambda: setattr(server, "should_exit", True)      # the page's QUIT button
        try:
            while not server.should_exit:
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.should_exit = True
        return

    import pystray
    def quit_app(icon, item):
        server.should_exit = True
        icon.stop()
    menu = pystray.Menu(
        pystray.MenuItem("Open LanceDeck", lambda icon, item: open_page(url), default=True),
        pystray.MenuItem("Setup", lambda icon, item: open_page(url + "setup")),
        pystray.MenuItem("Calibrate", lambda icon, item: open_page(url + "calib")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon(APP, _icon_image(), f"{APP} {VERSION} — {url}", menu)
    srv.quit_hook = lambda: quit_app(icon, None)                          # the page's QUIT button
    icon.run()


if __name__ == "__main__":
    main()
