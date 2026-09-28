"""What a loadout adds up to.

The target panel and the caster's highlight box print weapons in the game's own spelling,
which OCR then mangles a little ("6 x C-ER MED LASER", "C-UAC/10", "LB 10-X AC").  `norm`
folds every spelling onto one key of data/weapons.json (spaces, dashes and slashes gone,
MEDIUM/SMALL/LARGE/HEAVY shortened, "+ ARTEMIS" dropped, MACHINE GUN = MG), and `summary`
sums a loadout into the figures the competitive view shows: alpha damage, heat per alpha,
sustained damage per second, a damage-weighted optimal range and a band for it, and the
count per hardpoint type.  The figures are approximate by design (no ghost heat, quirks or
ammo); the table is the user's to edit.
"""
from __future__ import annotations

import json
import os
import re

from .paths import DATA

_PATH = os.path.join(DATA, "weapons.json")
_TABLE: dict[str, dict] | None = None
_INDEX: dict[str, str] = {}


def _compact(name: str) -> str:
    k = name.upper()
    k = re.sub(r"\+\s*ART(EMIS)?", "", k)
    k = k.replace("MEDIUM", "MED").replace("SMALL", "SML").replace("LARGE", "LRG").replace("HEAVY", "HVY")   # glued or not
    k = re.sub(r"MACHINE\s*GUN", "MG", k)
    k = re.sub(r"\bAUTOCANNON\b", "AC", k)
    k = re.sub(r"[\s\-/]+", "", k)
    k = re.sub(r"^CLAN", "C", k)
    k = re.sub(r"LB(\d+)X(AC)?", r"LB\1X", k)
    return k


def table() -> dict[str, dict]:
    global _TABLE
    if _TABLE is None:
        try:
            with open(_PATH, encoding="utf-8") as f:
                _TABLE = json.load(f).get("weapons", {})
        except Exception:
            _TABLE = {}
        _INDEX.clear()
        for k in _TABLE:
            _INDEX[_compact(k)] = k
        # spellings the game and OCR also produce
        for alias, key in (("HVYGAUSS", "HEAVY GAUSS RIFLE"), ("LTGAUSS", "LIGHT GAUSS RIFLE"), ("GAUSS", "GAUSS RIFLE"), ("CGAUSS", "C-GAUSS RIFLE"),
                           ("SNUBNOSEPPC", "SNUB PPC"), ("LPPC", "LIGHT PPC"), ("HPPC", "HEAVY PPC"), ("CERPPC", "C-ER PPC"),
                           ("SPL", "SML PULSE LASER"), ("MPL", "MED PULSE LASER"), ("LPL", "LRG PULSE LASER"),
                           ("CSPL", "C-SML PULSE LASER"), ("CMPL", "C-MED PULSE LASER"), ("CLPL", "C-LRG PULSE LASER"),
                           ("SL", "SML LASER"), ("ML", "MED LASER"), ("LL", "LRG LASER"), ("ERSL", "ER SML LASER"), ("ERML", "ER MED LASER"), ("ERLL", "ER LRG LASER"),
                           ("CERSL", "C-ER SML LASER"), ("CERML", "C-ER MED LASER"), ("CERLL", "C-ER LRG LASER"),
                           ("CHSL", "C-HVY SML LASER"), ("CHML", "C-HVY MED LASER"), ("CHLL", "C-HVY LRG LASER"),
                           ("STREAKSRM2", "SSRM 2"), ("STREAKSRM4", "SSRM 4"), ("STREAKSRM6", "SSRM 6"),
                           ("CSTREAKSRM2", "C-SSRM 2"), ("CSTREAKSRM4", "C-SSRM 4"), ("CSTREAKSRM6", "C-SSRM 6"),
                           ("RL10", "ROCKET LAUNCHER 10"), ("RL15", "ROCKET LAUNCHER 15"), ("RL20", "ROCKET LAUNCHER 20"),
                           ("XPULSELASER", "X-PULSE LASER"), ("SMLXPULSELASER", "X-PULSE LASER"), ("MEDXPULSELASER", "X-PULSE LASER"), ("LRGXPULSELASER", "X-PULSE LASER"),
                           ("ULTRAAC5", "UAC 5"), ("ULTRAAC10", "UAC 10"), ("ULTRAAC20", "UAC 20"), ("ULTRAAC2", "UAC 2"),
                           ("ROTARYAC2", "RAC 2"), ("ROTARYAC5", "RAC 5"), ("LBX10", "LB 10-X"), ("LBX20", "LB 20-X"), ("LBX5", "LB 5-X"), ("LBX2", "LB 2-X"),
                           ("CLBX10", "C-LB 10-X"), ("CLBX20", "C-LB 20-X"), ("CLBX5", "C-LB 5-X"), ("CLBX2", "C-LB 2-X"),
                           ("HAG20", "C-HAG 20"), ("HAG30", "C-HAG 30"), ("HAG40", "C-HAG 40"),
                           ("ATM3", "C-ATM 3"), ("ATM6", "C-ATM 6"), ("ATM9", "C-ATM 9"), ("ATM12", "C-ATM 12")):
            if key in _TABLE:
                _INDEX.setdefault(alias, key)
    return _TABLE


def norm(name: str) -> str | None:
    """The table key for a weapon as printed, or None when the table has no such weapon."""
    table()
    c = _compact(name)
    if c in _INDEX:
        return _INDEX[c]
    # a clan weapon printed without its C- ("ER MED LASER" in a clan mech's panel is still
    # the IS table row; the game prints C- for clan) — nothing to guess here
    return None


def summary(loadout: list[str] | None) -> dict | None:
    """The loadout summed up.  `loadout` lists one entry per weapon (repeats for counts).
    Returns None for an empty loadout; unknown weapons are counted but add nothing."""
    if not loadout:
        return None
    t = table()
    alpha = heat = dps = 0.0
    rng_w = 0.0
    types = {"E": 0, "B": 0, "M": 0, "S": 0}
    counts: dict[str, int] = {}
    unknown: list[str] = []
    for w in loadout:
        k = norm(w)
        label = k or w
        counts[label] = counts.get(label, 0) + 1
        if k is None:
            if w not in unknown:
                unknown.append(w)
            continue
        r = t[k]
        alpha += r["dmg"]; heat += r["heat"]
        if r["cd"] > 0:
            dps += r["dmg"] / r["cd"]
        rng_w += r["dmg"] * r["range"]
        types[r.get("type", "E")] = types.get(r.get("type", "E"), 0) + 1
    rng = round(rng_w / alpha) if alpha > 0 else 0
    band = "brawl" if rng and rng < 320 else "mid" if rng < 560 else "long" if rng else ""
    return {
        "alpha": round(alpha, 1), "heat": round(heat, 1), "dps": round(dps, 1), "range": rng, "band": band,
        "types": types, "weapons": [{"name": k, "n": n} for k, n in counts.items()],
        "unknown": unknown, "count": len(loadout),
    }
