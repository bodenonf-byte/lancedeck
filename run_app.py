"""LanceDeck — start the helper and open the page.  Ctrl+C in this window stops it."""
import json
import os
import shutil
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tracker.paths import CFG_PATH, CFG_DEFAULT, APP, VERSION, ensure_dirs


def main():
    ensure_dirs()
    if not os.path.exists(CFG_PATH):
        shutil.copyfile(CFG_DEFAULT, CFG_PATH)
    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    port = int(cfg.get("port", 8765))
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://localhost:{port}/"
    print(f"{APP} {VERSION} — {url}   (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    import uvicorn
    from tracker.server import app
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
