"""Run the picture harvester over the frames already in samples/ (CPU OCR, so it can run
while the live service holds the GPU)."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from tracker import harvest
from tracker.mechdb import MechDB
from tracker.ocr import Reader

db = MechDB(); reader = Reader(use_dml=False)
for f in sorted(glob.glob(os.path.join(harvest.ROOT, "samples", "mechlab_*.jpg")) + glob.glob(os.path.join(harvest.ROOT, "samples", "grid_*.jpg"))):
    img = Image.open(f).convert("RGB")
    lines = reader.read(img, 1.0)
    got = harvest.harvest_mech(img, lines, db) or harvest.harvest_grid(img, lines, db)
    print(os.path.basename(f), "->", got or ("home screen, no variant read" if harvest.is_home_screen(lines) else "not the home screen"))
