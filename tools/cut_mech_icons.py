"""Cut the mechs out of their hangar backdrop: assets/mechs/<X>.png -> assets/mechs/cut/<X>.png

Every MechLab icon is rendered in the same hangar, so the per-pixel median over all icons is
the backdrop.  Pixels that differ from it seed GrabCut, which refines the mask by colour, and
the biggest connected pieces are kept.  Re-run after import_game_icons.py; existing cut-outs
are skipped unless --force is given.

GrabCut seeds its colour model with k-means from OpenCV's global RNG, so the SAME icon could
cut differently on every run — a dark chassis against the dark hangar (Corsair, Bastion,
Cyclops) came out as a handful of fragments about half the time, and the page then stood an
almost invisible smudge on the pad (2026-09-23: "that mech doesnt show").  So each attempt now
runs on a fixed seed, the result is measured against the backdrop difference, and a cut that
keeps too little of the mech is retried on other seeds.  Nothing that fails the check is ever
written: with no cut-out the page falls back to the plain icon, which always shows the mech.

    python tools/cut_mech_icons.py [--force] [--repair] [--dir <assets folder>]

    --repair   measure the cut-outs that already exist, re-cut the poor ones, and move the
               ones that cannot be saved into cut/rejected/ (the page then uses the icon)
    --dir      work on another install's assets folder (e.g. a packaged build's)
"""
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
import numpy as np
from PIL import Image

from tracker.paths import ROOT, ASSETS
SRC = os.path.join(ASSETS, "mechs")
OUT = os.path.join(SRC, "cut")

# What a usable cut-out looks like, measured against the icon's own difference from the
# backdrop: it keeps most of what is certainly mech (`recall`), leaves out what is certainly
# hangar (`reject`), and covers a believable share of the frame.  Measured over the 1406
# icons of a full install, the good ones sit at recall 0.70-0.95 and the broken ones under
# 0.45, so the bar sits in the gap.
MIN_RECALL = 0.55
MIN_REJECT = 0.55
MIN_OPAQUE = 0.18
MAX_OPAQUE = 0.90
TRIES = 8


def backdrop(files):
    sample = files[::max(1, len(files) // 320)][:320]
    stack = np.stack([np.asarray(Image.open(f).convert("RGB").resize((256, 256)), dtype=np.uint8) for f in sample])
    return np.median(stack, axis=0).astype(int)


def difference(path, bg):
    """How far each pixel of an icon is from the hangar backdrop."""
    im = np.asarray(Image.open(path).convert("RGB").resize((256, 256)), dtype=int)
    return np.abs(im - bg).sum(axis=2)


def measure(alpha, diff):
    """(opaque share, recall of the certain mech, rejection of the certain hangar)."""
    m = np.asarray(alpha) > 127
    fg, bgp = diff > 60, diff < 12
    return (float(m.mean()),
            float(m[fg].mean()) if fg.any() else 0.0,
            float(1.0 - (m[bgp].mean() if bgp.any() else 0.0)))


def usable(q):
    op, recall, reject = q
    return recall >= MIN_RECALL and reject >= MIN_REJECT and MIN_OPAQUE <= op <= MAX_OPAQUE


def _cut_once(path, bg):
    rgb = np.asarray(Image.open(path).convert("RGB").resize((256, 256)), dtype=np.uint8)
    im = rgb.astype(int)
    diff = np.abs(im - bg).sum(axis=2); lum = im.mean(axis=2); blum = bg.mean(axis=2)
    strong = (diff > 70) | (lum > blum + 50)
    weak = (diff > 25) | (lum > blum + 18)
    mask = np.full(rgb.shape[:2], cv2.GC_PR_BGD, np.uint8)
    mask[weak] = cv2.GC_PR_FGD
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    core = cv2.erode(strong.astype(np.uint8), k, iterations=2).astype(bool)
    mask[core] = cv2.GC_FGD
    band = np.zeros_like(strong); band[:6, :] = True; band[-6:, :] = True; band[:, :6] = True; band[:, -6:] = True
    mask[band & ~weak] = cv2.GC_BGD
    if not core.any():
        return None
    bgd = np.zeros((1, 65), np.float64); fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n > 2:
        areas = stats[1:, cv2.CC_STAT_AREA]; big = areas.max(); keep = np.zeros_like(m)
        for i, a in enumerate(areas):
            if a >= 0.05 * big:
                keep[lab == i + 1] = 255
        m = keep
    if m.mean() < 8:                                       # nothing much kept: not a usable cut-out
        return None
    m = cv2.GaussianBlur(m, (3, 3), 0.8)
    return Image.fromarray(np.dstack([rgb, m]), "RGBA")


def cut(path, bg, tries: int = TRIES, diff=None):
    """The best cut-out this icon gives, or None when none of the attempts is usable."""
    if diff is None:
        diff = difference(path, bg)
    best, best_score, best_q = None, None, None
    for seed in range(max(1, tries)):
        cv2.setRNGSeed(seed)                   # without this the same icon cuts differently every run
        try:
            im = _cut_once(path, bg)
        except Exception:
            im = None
        if im is None:
            continue
        q = measure(im.getchannel("A"), diff)
        score = q[1] + q[2] - 4 * max(0.0, q[0] - MAX_OPAQUE)   # keep the mech, drop the hangar
        if best_score is None or score > best_score:
            best, best_score, best_q = im, score, q
        if usable(q) and q[1] > 0.70:          # good enough: no need to spend more seeds
            break
    if best is None or not usable(best_q):
        return None
    return best


def main():
    argv = sys.argv[1:]
    force = "--force" in argv
    repair = "--repair" in argv
    global SRC, OUT
    if "--dir" in argv:
        base = argv[argv.index("--dir") + 1]
        SRC = os.path.join(base, "mechs"); OUT = os.path.join(SRC, "cut")
    files = sorted(f for f in glob.glob(os.path.join(SRC, "*.png")) if os.path.dirname(f) == SRC)
    if not files:
        print("no icons in", SRC); return 1
    os.makedirs(OUT, exist_ok=True)
    bg = backdrop([f for f in files if "-" in os.path.basename(f)] or files)
    done = skipped = failed = repaired = dropped = 0
    for i, f in enumerate(files):
        name = os.path.basename(f)
        out = os.path.join(OUT, name)
        if os.path.exists(out) and not force and not repair:
            skipped += 1; continue
        diff = None
        if os.path.exists(out) and repair and not force:    # keep a cut-out that is already good
            try:
                diff = difference(f, bg)
                if usable(measure(Image.open(out).convert("RGBA").getchannel("A"), diff)):
                    skipped += 1; continue
            except Exception:
                pass
        try:
            im = cut(f, bg, diff=diff)
        except Exception as e:
            print("  fail", name, e); failed += 1; continue
        if im is None:
            # nothing usable.  An existing bad cut-out has to go, or the page keeps standing
            # a fragment on the pad; the icon underneath always shows the whole mech.
            if os.path.exists(out):
                rej = os.path.join(OUT, "rejected"); os.makedirs(rej, exist_ok=True)
                shutil.move(out, os.path.join(rej, name)); dropped += 1
                print(f"  no usable cut for {name[:-4]} -> the page will show the plain icon")
            failed += 1; continue
        was = os.path.exists(out)
        im.save(out, optimize=True)
        if was:
            repaired += 1
            print(f"  re-cut {name[:-4]}")
        else:
            done += 1
        if (done + repaired) % 100 == 0:
            print(f"  {done + repaired} cut, {i + 1}/{len(files)} seen", flush=True)
    print(f"cut {done}, re-cut {repaired}, dropped {dropped}, skipped {skipped}, unusable {failed} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
