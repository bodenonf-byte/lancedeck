"""Copy the mech icons out of your own MechWarrior Online install into assets/mechs.

The game ships one PNG per variant in GameData.pak (Libs/UI/Screens/Assets/MechIcons/
as7-d-dc.png ...).  Nothing is downloaded: the pictures are read from the game you have
installed and stay on this machine.  Re-run after a game patch to pick up new mechs.

  python tools/import_game_icons.py            # default Steam location
  python tools/import_game_icons.py "D:\\Games\\MechWarrior Online"
"""
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from tracker.mechdb import MechDB

from tracker.paths import ROOT, ASSETS
OUT = os.path.join(ASSETS, "mechs")
CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\MechWarrior Online",
    r"C:\Games\Piranha Games\MechWarrior Online",
    r"D:\SteamLibrary\steamapps\common\MechWarrior Online",
]
ICON_DIR = "Libs/UI/Screens/Assets/MechIcons/"


def find_game(arg: str | None) -> str | None:
    """The install folder: the one given, else the usual Steam and standalone places, else the
    Steam library folders listed by Steam itself."""
    cands = ([arg] if arg else []) + CANDIDATES
    try:
        vdf = r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf"
        if os.path.exists(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="ignore").read()):
                cands.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps", "common", "MechWarrior Online"))
    except Exception:
        pass
    for d in cands:
        if d and os.path.isfile(os.path.join(d, "Game", "GameData.pak")):
            return d
    return None


def main():
    game = find_game(sys.argv[1] if len(sys.argv) > 1 else None)
    if not game:
        print("MechWarrior Online not found — pass its folder as the first argument"); return 1
    db = MechDB()
    z = zipfile.ZipFile(os.path.join(game, "Game", "GameData.pak"))
    icons = [n for n in z.namelist() if n.startswith(ICON_DIR) and n.lower().endswith(".png")]
    os.makedirs(OUT, exist_ok=True)
    written = 0; unknown = []; per_chassis: dict[str, list[tuple[str, str]]] = {}
    for n in icons:
        stem = os.path.splitext(os.path.basename(n))[0].upper()          # AS7-D-DC
        hit = db.lookup(stem)
        if not hit or hit[2] < 0.9:
            unknown.append(stem); continue
        chassis, variant, _ = hit
        variant = re.sub(r"[^A-Z0-9\-]", "", variant)
        name = f"{chassis.code}-{variant}.png" if variant else f"{chassis.code}.png"
        try:
            im = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
        except Exception as e:
            print("  skip", n, e); continue
        im.save(os.path.join(OUT, name), optimize=True); written += 1
        per_chassis.setdefault(chassis.code, []).append((variant, name))
    # the chassis picture: the PRIME / plainest variant stands for the chassis
    for code, vs in per_chassis.items():
        vs.sort(key=lambda v: (0 if v[0] in ("PRIME", "") else 1, len(v[0]), v[0]))
        src = os.path.join(OUT, vs[0][1])
        Image.open(src).save(os.path.join(OUT, f"{code}.png"), optimize=True)
    print(f"{written} variant icons for {len(per_chassis)} chassis written to {OUT}")
    if unknown:
        print(f"{len(unknown)} icons whose code is not in data/mechs.json:", ", ".join(sorted(set(unknown))[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
