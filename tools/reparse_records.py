"""Re-read the end screens kept under records/ with the current parser and patch the records:
damage dealt (the DMG column) and the map name.  Scores, medals, results and rosters are left
as they were.  CPU OCR, so it can run beside the live helper.

  python tools/reparse_records.py            # patch every record that has its .jpg
  python tools/reparse_records.py --dry      # only say what would change
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from tracker.match import build, detect_map
from tracker.mechdb import MechDB
from tracker.ocr import Reader
from tracker.paths import CFG_PATH, RECORDS

dry = "--dry" in sys.argv


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


cfg = {}
if os.path.exists(CFG_PATH):
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
db = MechDB(); reader = Reader(use_dml=False, threads=int(cfg.get("ocr_threads", 4) or 4))

for jp in sorted(glob.glob(os.path.join(RECORDS, "*.json"))):
    ip = jp[:-5] + ".jpg"
    if not os.path.exists(ip):
        continue
    with open(jp, encoding="utf-8") as f:
        rec = json.load(f)
    img = Image.open(ip).convert("RGB")
    lines = reader.read(img, float(cfg.get("ocr_scale", 1.0)))
    raw = build(lines, img, db, cfg, "record")
    texts = [l.text for l in lines]
    changes = []
    if raw.kind == "scoreboard":
        read = {}
        for s in raw.mine + raw.enemy:
            if s.damage is not None and key(s.pilot):
                read[key(s.pilot)] = s.damage
        for side in ("mine", "enemy"):
            for s in rec.get(side, []):
                k = key(s.get("pilot"))
                # names come back slightly different between reads: exact, then contains
                d = read.get(k)
                if d is None and len(k) >= 4:
                    d = next((v for kk, v in read.items() if len(kk) >= 4 and (k in kk or kk in k)), None)
                if d is not None and s.get("damage") != d:
                    changes.append(f"{s.get('pilot')}: DMG {s.get('damage')} -> {d}")
                    s["damage"] = d
    m = raw.map or detect_map([t.upper() for t in texts])
    if m and not rec.get("map"):
        changes.append(f"map -> {m}")
        rec["map"] = m
    name = os.path.basename(jp)
    if not changes:
        print(name, "unchanged" if raw.kind == "scoreboard" else f"not a results screen ({raw.kind})")
        continue
    print(name, "|", "; ".join(changes))
    if not dry:
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
