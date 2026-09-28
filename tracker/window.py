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


# ── any window, not just the game ────────────────────────────────────────────────────────
# A caster's match is not in the game client: it is a stream in a browser, or a spectator
# client, or a capture program, often on another screen.  So the reader has to be able to
# look at a window the user picks, or at a whole monitor.

def _process_name(hwnd: int) -> str:
    """The exe behind a window, so a list of titles is recognisable ("chrome.exe")."""
    try:
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        k32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            n = wt.DWORD(512)
            if k32.QueryFullProcessImageNameW(ctypes.c_void_p(h), 0, buf, ctypes.byref(n)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        pass
    return ""


def _window_of(hwnd: int, title: str) -> GameWindow | None:
    rc = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    if rc.right <= 0 or rc.bottom <= 0:
        return None
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    rect = (pt.x, pt.y, pt.x + rc.right, pt.y + rc.bottom)
    cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    mons = _monitors()
    idx = 0
    for i, m in enumerate(mons):
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            idx = i
            break
    return GameWindow(hwnd, title, rect, mons[idx] if mons else (0, 0, 0, 0), idx + 1)


def list_windows(min_side: int = 320) -> list[dict]:
    """Every visible titled window big enough to hold a match, biggest first."""
    out: list[dict] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        gw = _window_of(hwnd, buf.value)
        if gw is None:
            return True
        w, h = gw.rect[2] - gw.rect[0], gw.rect[3] - gw.rect[1]
        if w < min_side or h < min_side:
            return True
        out.append({"hwnd": int(hwnd), "title": gw.title, "app": _process_name(hwnd),
                    "size": [w, h], "monitor": gw.monitor_index,
                    "game": any(x in gw.title.lower() for x in TITLE_WORDS)})
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    out.sort(key=lambda d: (not d["game"], -d["size"][0] * d["size"][1]))
    return out


def find_by_hwnd(hwnd: int) -> GameWindow | None:
    if not hwnd or not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return _window_of(hwnd, buf.value)


def find_by_app(app: str) -> GameWindow | None:
    """The biggest visible window belonging to this exe — so an aim survives the stream's
    browser being closed and opened again, which gives the window a new handle."""
    app = (app or "").strip().lower()
    if not app:
        return None
    hits = [w for w in list_windows() if (w["app"] or "").lower() == app]
    return find_by_hwnd(hits[0]["hwnd"]) if hits else None


def find_by_title(part: str) -> GameWindow | None:
    """The biggest visible window whose title contains this text (case does not matter)."""
    part = (part or "").strip().lower()
    if not part:
        return None
    hits = [w for w in list_windows() if part in w["title"].lower()]
    return find_by_hwnd(hits[0]["hwnd"]) if hits else None
