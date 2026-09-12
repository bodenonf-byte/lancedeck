"""Screen grabs, aimed at the game.

`window.find_game()` says which monitor MechWarrior Online is on and where its client
rectangle is; the grabber reads that monitor with `dxcam` (Desktop Duplication: sees
exclusive fullscreen, ~1 ms for a region, ~50 ms for 3440x1440) and takes regions as
fractions OF THE GAME WINDOW, so the lance-panel corner is the game's corner whether the
game is fullscreen, borderless, windowed, or on a second screen.  `mss` is the fallback.
"""
from __future__ import annotations

import threading
import time

from PIL import Image

from . import window


class Grabber:
    def __init__(self, monitor: int = 1):
        self.lock = threading.Lock()
        self.backend = "mss"
        self.cams: dict[int, object] = {}
        self.default_monitor = monitor
        self.window_mode = True          # capture the window's own surface; False = always the screen region
        self.backend_now = "window"
        self._screen_until = 0.0
        self.game: window.GameWindow | None = None
        self.mon_rect: tuple[int, int, int, int] | None = None
        self.win_rect: tuple[int, int, int, int] | None = None
        self.mon_index = monitor
        self._next_locate = 0.0
        try:
            import dxcam
            self.dxcam = dxcam
            self.backend = "dxcam"
        except Exception:
            self.dxcam = None
        import mss
        self.sct = mss.mss()
        self.locate(force=True)

    # ── where ────────────────────────────────────────────────────────────────
    def locate(self, force: bool = False):
        """Re-find the game every few seconds (it may start, move, or go windowed)."""
        now = time.time()
        if not force and now < self._next_locate:
            return
        self._next_locate = now + 3.0
        mons = window.monitors()
        gw = window.find_game()
        self.game = gw
        if gw is not None:
            self.mon_index = gw.monitor_index; self.mon_rect = gw.monitor
            r = gw.rect; m = gw.monitor
            self.win_rect = (max(r[0], m[0]), max(r[1], m[1]), min(r[2], m[2]), min(r[3], m[3]))
        else:
            # no game window: read NOTHING.  Falling back to the whole monitor used to OCR
            # whatever was on the desktop (a browser with old screenshots) into the roster.
            idx = min(max(1, self.default_monitor), max(1, len(mons)))
            self.mon_index = idx
            self.mon_rect = mons[idx - 1] if mons else (0, 0, 1920, 1080)
            self.win_rect = None

    def _cam(self):
        """The dxcam output whose size matches the target monitor (dxcam's order can differ)."""
        if self.dxcam is None or self.mon_rect is None:
            return None
        want = (self.mon_rect[2] - self.mon_rect[0], self.mon_rect[3] - self.mon_rect[1])
        for idx in range(0, 6):
            try:
                cam = self.cams.get(idx)
                if cam is None:
                    cam = self.dxcam.create(output_idx=idx, output_color="RGB")
                    if cam is None:
                        break
                    self.cams[idx] = cam
                if (int(cam.width), int(cam.height)) == want:
                    return cam
            except Exception:
                break
        return self.cams.get(0)

    def size(self) -> tuple[int, int]:
        r = self.win_rect or (0, 0, 1920, 1080)
        return r[2] - r[0], r[3] - r[1]

    def describe(self) -> dict:
        return {"backend": self.backend_now, "monitor": self.mon_index, "monitor_rect": self.mon_rect,
                "window": self.game.title if self.game else None, "window_rect": self.win_rect}

    # ── grab ─────────────────────────────────────────────────────────────────
    def grab(self, region: tuple[float, float, float, float] | None = None) -> Image.Image | None:
        """The game window, or a region of it given as fractions (x0, y0, x1, y1).

        First choice: the window's own surface through the Desktop Window Manager (PrintWindow),
        which holds only the game whatever other windows cover it — the way OBS's window capture
        works, without touching the game.  An exclusive-fullscreen game has no such surface and
        comes back black; then, and only then, the screen region is read instead (nothing can
        cover an exclusive-fullscreen game)."""
        self.locate()
        m = self.mon_rect; w = self.win_rect
        if m is None or w is None:
            return None
        if self.game is not None and self.window_mode and time.time() >= self._screen_until:
            try:
                from . import wincap
                img = wincap.grab_window(self.game.hwnd, region)
            except Exception:
                img = None
            if img is not None and not wincap.looks_black(img):
                self.backend_now = "window"
                return img
            self._screen_until = time.time() + 10.0     # black or failed: exclusive fullscreen, use the screen for a while
        self.backend_now = self.backend
        if region is None:
            box = (w[0] - m[0], w[1] - m[1], w[2] - m[0], w[3] - m[1])
        else:
            ww, wh = w[2] - w[0], w[3] - w[1]
            box = (w[0] - m[0] + int(region[0] * ww), w[1] - m[1] + int(region[1] * wh),
                   w[0] - m[0] + int(region[2] * ww), w[1] - m[1] + int(region[3] * wh))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            return None
        with self.lock:
            cam = self._cam()
            if cam is not None:
                try:
                    arr = cam.grab(region=box)
                except Exception:
                    arr = None
                if arr is not None:
                    return Image.fromarray(arr)
                if self.backend == "dxcam":
                    return None                     # no new frame: the picture has not changed
            mon = {"left": m[0] + box[0], "top": m[1] + box[1], "width": box[2] - box[0], "height": box[3] - box[1]}
            shot = self.sct.grab(mon)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
