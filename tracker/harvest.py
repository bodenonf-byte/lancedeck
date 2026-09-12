"""Pictures harvested from the player's own screen — never downloaded.

* Mech portraits: the MechLab home screen shows the selected mech centred in the hangar with
  a "CURRENTLY SELECTED BATTLEMECH" panel naming the variant.  When the full-frame loop sees
  that panel it crops the mech out of the middle of the frame and keeps it as
  assets/mechs/<CODE>.png (the chassis) and assets/mechs/<CODE>-<VARIANT>.png.  Browse your
  mechs in the MechLab once and the board fills with their pictures.
* Map backdrops: some 45 s into a match on a map with no picture yet, one gameplay frame is
  kept as assets/maps/<map-slug>.jpg and becomes the page background for that map.
"""
from __future__ import annotations

import os
import re

from PIL import Image

from .paths import ROOT, ASSETS
MECHS = os.path.join(ASSETS, "mechs")
MAPS = os.path.join(ASSETS, "maps")

HOME_WORDS = ("CURRENTLY SELECTED BATTLEMECH", "CURRENTLY SELECTED", "SELECTED BATTLEMECH")
# where the mech stands on the home screen, as fractions of the frame (3440x1440 measured)
PORTRAIT = (0.405, 0.25, 0.595, 0.86)
_LAST: dict[str, str] = {}


def slug(m: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (m or "").lower()).strip("-")


def is_home_screen(lines) -> bool:
    text = " ".join(l.text for l in lines).upper()
    return any(w in text for w in HOME_WORDS)


def _variant_line(lines, db, h: int):
    """The variant named in the bottom panel: a token on a line in the lower fifth of the frame."""
    from .mechdb import find_tokens
    best = None
    for l in lines:
        if l.cy < h * 0.78:
            continue
        for _, _, tok in find_tokens(l.text):
            hit = db.lookup(tok)
            if hit and (best is None or hit[2] > best[2]):
                best = (hit[0], hit[1], hit[2])
    return best


def harvest_mech(img: Image.Image, lines, db) -> list[str]:
    """Save the mech in the middle of a MechLab home screen; returns the files written."""
    if not is_home_screen(lines):
        return []
    hit = _variant_line(lines, db, img.height)
    if hit is None or hit[2] < 0.8:
        return []
    chassis, variant, _ = hit
    code = chassis.code
    # a variant file only when two reads in a row agree on the variant (OCR turns 4X into 4K);
    # the chassis file needs no such care, the prefix alone names it
    steady = variant and variant == _LAST.get(code)
    _LAST[code] = variant
    if not steady:
        variant = ""
    w, h = img.size
    box = (int(w * PORTRAIT[0]), int(h * PORTRAIT[1]), int(w * PORTRAIT[2]), int(h * PORTRAIT[3]))
    crop = img.crop(box)
    if crop.width > 640:
        crop = crop.resize((640, int(crop.height * 640 / crop.width)), Image.LANCZOS)
    os.makedirs(MECHS, exist_ok=True)
    out = []
    names = [f"{code}.png"] + ([f"{code}-{variant}.png"] if variant else [])
    for name in names:
        if os.path.exists(os.path.join(MECHS, name)):
            continue                                   # the game's own icon (or an earlier capture) stays
        crop.save(os.path.join(MECHS, name), optimize=True)
        out.append(name)
    return out


# the front-end (MechLab/home/store) always carries the top navigation; a match never does
FRONTEND_WORDS = ("QUICK PLAY", "FACTION PLAY", "COMP PLAY", "MECHLAB")
_NAME_CACHE: dict[int, dict[str, str]] = {}


def _names(db) -> dict[str, str]:
    """Chassis name (letters only, upper) -> code, for the labels under the grid tiles."""
    key = id(db)
    if key not in _NAME_CACHE:
        m = {}
        for code, c in db.chassis.items():
            m[re.sub(r"[^A-Z]", "", c.name.upper())] = code
        _NAME_CACHE[key] = m
    return _NAME_CACHE[key]


def is_frontend(lines) -> bool:
    text = " ".join(l.text for l in lines).upper()
    return any(w in text for w in FRONTEND_WORDS)


def grid_labels(lines, db) -> list[tuple[str, object]]:
    """(code, line) for every OCR line that is a chassis name or a variant token on a grid tile."""
    from .mechdb import find_tokens
    names = _names(db)
    out = []
    for l in lines:
        t = l.text.upper()
        letters = re.sub(r"[^A-Z]", "", re.sub(r"\(.*?\)", "", t))       # "TIMBER WOLF (C)" -> TIMBERWOLF
        code = names.get(letters)
        if code is None and 4 <= len(letters) <= 18:
            # one OCR slip allowed on a long name
            import difflib
            hit = difflib.get_close_matches(letters, names.keys(), n=1, cutoff=0.9)
            if hit:
                code = names[hit[0]]
        if code is None:
            toks = [tok for _, _, tok in find_tokens(t)]
            if len(toks) == 1 and len(t.strip()) <= len(toks[0]) + 4:      # the line IS the variant code
                hit = db.lookup(toks[0])
                if hit and hit[2] >= 0.9:
                    code = hit[0].code
        if code:
            out.append((code, l))
    return out


def harvest_grid(img: Image.Image, lines, db) -> list[str]:
    """On a MechLab grid, cut the tile above each mech label.  Only fills chassis that have
    no picture yet — the centred home-screen portrait is better and always wins."""
    if not is_frontend(lines):
        return []
    labels = grid_labels(lines, db)
    if len(labels) < 3:
        return []                                      # not a grid: the home screen, a loadout, chat
    w, h = img.size
    # the tile size: the labels of one grid sit in columns; the typical gap between neighbouring
    # label centres on the same row is the tile pitch
    xs = sorted({(l.x0 + l.x1) / 2 for _, l in labels})
    gaps = [b - a for a, b in zip(xs, xs[1:]) if b - a > 40]
    pitch = min(gaps) if gaps else max(l.x1 - l.x0 for _, l in labels) * 1.6
    side = int(max(120, min(pitch * 0.92, w * 0.2)))
    os.makedirs(MECHS, exist_ok=True)
    out = []
    for code, l in labels:
        path = os.path.join(MECHS, f"{code}.png")
        if os.path.exists(path):
            continue
        cx = (l.x0 + l.x1) / 2
        x0 = int(max(0, cx - side / 2)); y1 = int(max(0, l.y0 - 4)); y0 = int(max(0, y1 - side))
        if y1 - y0 < side * 0.6:
            continue                                   # the tile is cut by the top of the frame
        crop = img.crop((x0, y0, min(w, x0 + side), y1))
        if crop.width > 512:
            crop = crop.resize((512, int(crop.height * 512 / crop.width)), Image.LANCZOS)
        crop.save(path, optimize=True); out.append(f"{code}.png")
    return out


def have_map(map_name: str) -> bool:
    s = slug(map_name)
    return bool(s) and os.path.isdir(MAPS) and any(f.lower().startswith(s) for f in os.listdir(MAPS))


def harvest_map(img: Image.Image, map_name: str) -> str | None:
    """Keep one gameplay frame as the backdrop of this map (once; delete the file to refresh)."""
    s = slug(map_name)
    if not s or have_map(map_name):
        return None
    os.makedirs(MAPS, exist_ok=True)
    im = img
    if im.width > 1720:
        im = im.resize((1720, int(im.height * 1720 / im.width)), Image.LANCZOS)
    path = os.path.join(MAPS, s + ".jpg")
    im.convert("RGB").save(path, quality=80, optimize=True)
    return s + ".jpg"
