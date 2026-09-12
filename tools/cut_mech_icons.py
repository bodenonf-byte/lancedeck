"""Cut the mechs out of their hangar backdrop: assets/mechs/<X>.png -> assets/mechs/cut/<X>.png

Every MechLab icon is rendered in the same hangar, so the per-pixel median over all icons is
the backdrop.  Pixels that differ from it seed GrabCut, which refines the mask by colour, and
the biggest connected pieces are kept.  Re-run after import_game_icons.py; existing cut-outs
are skipped unless --force is given.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cv2
import numpy as np
from PIL import Image

from tracker.paths import ROOT, ASSETS
SRC = os.path.join(ASSETS, "mechs")
OUT = os.path.join(SRC, "cut")


def backdrop(files):
    sample = files[::max(1, len(files) // 320)][:320]
    stack = np.stack([np.asarray(Image.open(f).convert("RGB").resize((256, 256)), dtype=np.uint8) for f in sample])
    return np.median(stack, axis=0).astype(int)


def cut(path, bg):
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


def main():
    force = "--force" in sys.argv
    files = sorted(f for f in glob.glob(os.path.join(SRC, "*.png")) if os.path.dirname(f) == SRC)
    if not files:
        print("no icons in", SRC); return 1
    os.makedirs(OUT, exist_ok=True)
    bg = backdrop([f for f in files if "-" in os.path.basename(f)] or files)
    done = skipped = failed = 0
    for i, f in enumerate(files):
        out = os.path.join(OUT, os.path.basename(f))
        if os.path.exists(out) and not force:
            skipped += 1; continue
        try:
            im = cut(f, bg)
        except Exception as e:
            print("  fail", os.path.basename(f), e); failed += 1; continue
        if im is None:
            failed += 1; continue
        im.save(out, optimize=True); done += 1
        if done % 100 == 0:
            print(f"  {done} cut, {i + 1}/{len(files)} seen", flush=True)
    print(f"cut {done}, skipped {skipped}, unusable {failed} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
