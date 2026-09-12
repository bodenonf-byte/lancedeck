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
            webbrowser.open(url)
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
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()

    if console:
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
        pystray.MenuItem("Open LanceDeck", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem("Setup", lambda icon, item: webbrowser.open(url + "setup")),
        pystray.MenuItem("Calibrate", lambda icon, item: webbrowser.open(url + "calib")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    pystray.Icon(APP, _icon_image(), f"{APP} {VERSION} — {url}", menu).run()


if __name__ == "__main__":
    main()
