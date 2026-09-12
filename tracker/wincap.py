"""Capture one window's own pixels, whatever sits on top of it.

`PrintWindow(hwnd, PW_RENDERFULLCONTENT)` asks the Desktop Window Manager for the window's
composed surface: only that window, never the windows covering it.  That is how OBS's
"Window Capture" isolates a game without injecting anything into it.  Works for windowed and
borderless-fullscreen games; an exclusive-fullscreen game has no composed surface and comes
back black — in that mode nothing can cover the game anyway, so the caller falls back to the
screen capture.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def client_size(hwnd: int) -> tuple[int, int]:
    r = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right - r.left, r.bottom - r.top


def grab_window(hwnd: int, region: tuple[float, float, float, float] | None = None) -> Image.Image | None:
    """The window's client area as an RGB image, or a region of it in fractions; None on failure."""
    w, h = client_size(hwnd)
    if w < 8 or h < 8:
        return None
    hdc = user32.GetDC(hwnd)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h                    # top-down rows
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bits = ctypes.c_void_p()
    hbm = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    try:
        if not hbm:
            return None
        old = gdi32.SelectObject(mem, hbm)
        ok = user32.PrintWindow(hwnd, mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        gdi32.SelectObject(mem, old)
        if not ok:
            return None
        buf = ctypes.string_at(bits, w * h * 4)
        img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        if region is not None:
            img = img.crop((int(region[0] * w), int(region[1] * h), int(region[2] * w), int(region[3] * h)))
        return img.copy()
    finally:
        if hbm:
            gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def looks_black(img: Image.Image) -> bool:
    """An exclusive-fullscreen game renders nothing through the DWM: the capture is black."""
    small = img.convert("L").resize((64, 36))
    return max(small.getdata()) < 12
