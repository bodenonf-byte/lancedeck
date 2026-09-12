"""Where the game is.  Finds the MechWarrior Online window by title and reports the monitor
it sits on and its client rectangle, so the grabber reads that monitor and only the
window's own pixels — windowed, borderless, or on a second screen.  Pure ctypes; nothing to
install.  Falls back to the primary monitor when no game window is up.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

user32 = ctypes.windll.user32
TITLE_WORDS = ("mechwarrior online", "mwo client", "mwoclient")

# Per-monitor DPI awareness FIRST, or Windows hands this process scaled coordinates (a
# 3440x1440 display at 150 % reads as 2293x960) while the grabber sees physical pixels.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class GameWindow:
    hwnd: int
    title: str
    rect: tuple[int, int, int, int]        # client area in screen pixels (left, top, right, bottom)
    monitor: tuple[int, int, int, int]     # the monitor's rectangle
    monitor_index: int                     # 1-based, in EnumDisplayMonitors order (primary first when it is first)


def is_foreground(hwnd: int) -> bool:
    """Is this the window in front (the one with the keyboard)?  The screen shows the game
    only then; an exclusive-fullscreen game that lost the front is minimised anyway."""
    try:
        return int(user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _monitors() -> list[tuple[int, int, int, int]]:
    mons: list[tuple[int, int, int, int]] = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, lprc, lparam):
        r = lprc.contents
        mons.append((r.left, r.top, r.right, r.bottom))
        return 1
    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0)
    # primary (origin 0,0) first, then left-to-right
    mons.sort(key=lambda m: (0 if (m[0], m[1]) == (0, 0) else 1, m[0], m[1]))
    return mons


def find_game() -> GameWindow | None:
    found: list[tuple[int, str]] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        t = buf.value
        if any(w in t.lower() for w in TITLE_WORDS):
            found.append((hwnd, t))
        return True
    user32.EnumWindows(EnumWindowsProc(cb), 0)
    if not found:
        return None
    hwnd, title = found[0]
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    rect = (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)
    if rc.right <= 0 or rc.bottom <= 0:
        return None
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    mons = _monitors()
    idx = 0
    for i, m in enumerate(mons):
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            idx = i; break
    return GameWindow(hwnd, title, rect, mons[idx] if mons else (0, 0, 0, 0), idx + 1)


def monitors() -> list[tuple[int, int, int, int]]:
    return _monitors()
