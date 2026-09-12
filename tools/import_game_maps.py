"""Copy the maps' loading-screen art out of your MechWarrior Online install into assets/maps.

GameData.pak holds Levels/<level>/loading_<level>.dds (2048x1024) for every map.  The level
folder names are the game's internal ones; LEVELS maps them to the names the loading screen
prints, which is what the tracker reads.  Nothing is downloaded.

  python tools/import_game_maps.py            # default Steam location
  python tools/import_game_maps.py "D:\\Games\\MechWarrior Online"
"""
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image

from tools.import_game_icons import find_game

from tracker.paths import ROOT, ASSETS
OUT = os.path.join(ASSETS, "maps")

# level folder -> map name as printed in game
LEVELS = {
    "alpinepeaks": "Alpine Peaks", "bearclaw": "Bearclaw", "canyonnetwork": "Canyon Network",
    "causticvalley": "Caustic Valley", "forestcolony": "Forest Colony", "frozencity": "Frozen City",
    "polarhighlands": "Polar Highlands", "rivercity": "River City", "tourmalinedesert": "Tourmaline Desert",
    "terraceswamp": "Viridian Bog", "lavaworld": "Terra Therma", "moonbase": "HPG Manifold",
    "islandmetropolis": "Crimson Strait", "crater2": "Rubellite Oasis", "icelavanetwork": "Hibernal Rift",
    "mountain": "Emerald Taiga", "gorge": "Hellebore Springs", "spacebase": "Vitric Forge",
    "badlands": "Sulfurous Rift", "bismuth": "Grim Plexus", "frost": "Boreal Vault",
    "CapitolCity": "Solaris City", "GorgeOasis": "Free Worlds Coliseum", "luthien": "Luthien",
    "Scrapyard": "Ceres Metal Scrapyard", "mechfactory": "Mech Factory",
    "MountainQP": "Emerald Vale", "GorgeQP": "Hellebore Outpost", "spacebaseQP": "Vitric Station", "LavaworldQP": "Terra Therma Crucible",
}


def slug(m: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", m.lower()).strip("-")


def main():
    game = find_game(sys.argv[1] if len(sys.argv) > 1 else None)
    if not game:
        print("MechWarrior Online not found — pass its folder as the first argument"); return 1
    z = zipfile.ZipFile(os.path.join(game, "Game", "GameData.pak"))
    loads = {}
    for n in z.namelist():
        m = re.match(r"^Levels/([^/]+)/loading_[^/]+\.dds$", n)
        if m:
            loads.setdefault(m.group(1), n)
    os.makedirs(OUT, exist_ok=True)
    done = 0
    for folder, name in LEVELS.items():
        src = loads.get(folder)
        if not src:
            print("  no loading art for", folder, "(" + name + ")"); continue
        im = Image.open(io.BytesIO(z.read(src))).convert("RGB")
        if im.width > 1720:
            im = im.resize((1720, int(im.height * 1720 / im.width)), Image.LANCZOS)
        im.save(os.path.join(OUT, slug(name) + ".jpg"), quality=86, optimize=True); done += 1
    print(f"{done} map backdrops written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
