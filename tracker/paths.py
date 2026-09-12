"""Where things live, in a checkout and in the packaged app.

RES   bundled, read-only: web/, data/, tools/, the default config
ROOT  writable, next to the executable (or the checkout): config.json, assets/, records/,
      samples/, sightings.log
"""
import os
import sys

APP = "LanceDeck"
VERSION = "0.9.2"
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
    RES = getattr(sys, "_MEIPASS", ROOT)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RES = ROOT

WEB = os.path.join(RES, "web")
DATA = os.path.join(RES, "data")
TOOLS = os.path.join(RES, "tools")
ASSETS = os.path.join(ROOT, "assets")
RECORDS = os.path.join(ROOT, "records")
SAMPLES = os.path.join(ROOT, "samples")
CFG_PATH = os.path.join(ROOT, "config.json")
CFG_DEFAULT = os.path.join(RES, "tracker", "config.default.json")
LOG = os.path.join(ROOT, "sightings.log")


def ensure_dirs() -> None:
    for d in (ASSETS, os.path.join(ASSETS, "mechs"), os.path.join(ASSETS, "maps"), RECORDS, SAMPLES):
        os.makedirs(d, exist_ok=True)
