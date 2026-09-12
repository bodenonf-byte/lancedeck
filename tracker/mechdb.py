"""The mech database: chassis keyed by the scoreboard's variant-code prefix.

A MechWarrior Online scoreboard prints a variant code such as ``TBR-PRIME``, ``AS7-D-DC``,
``HBK-IIC-A`` or ``HBR-F(L)``.  The prefix before the first dash names the chassis (the IIC
chassis carry the dash inside their name, handled by aliases); the rest names the variant.
OCR gets the prefix mostly right and the suffix less so, so matching leans on the prefix and
keeps the raw suffix for display.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
from .paths import DATA as _DATA_DIR
DATA = os.path.join(_DATA_DIR, "mechs.json")

CLASS_ORDER = {"Light": 0, "Medium": 1, "Heavy": 2, "Assault": 3, "Unknown": 4}


@dataclass
class Chassis:
    code: str
    name: str
    tons: int
    cls: str
    faction: str
    pros: str
    cons: str


class MechDB:
    def __init__(self, path: str = DATA):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.chassis: dict[str, Chassis] = {}
        for code, c in raw["chassis"].items():
            self.chassis[code] = Chassis(code, c["name"], c["tons"], c["class"], c["faction"], c["pros"], c["cons"])
        for code, c in raw.get("chassis_extra", {}).items():
            self.chassis[code] = Chassis(code, c["name"], c["tons"], c["class"], c["faction"], c["pros"], c["cons"])
        # aliases map a full variant prefix (e.g. "HBK-IIC") to a chassis key; longest first
        self.aliases: list[tuple[str, str]] = sorted(raw.get("aliases", {}).items(), key=lambda kv: -len(kv[0]))
        self.codes = [c for c in self.chassis if len(c) >= 2]

    # OCR confusions that matter for short upper-case codes
    _FIX = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I"})

    @staticmethod
    def normalise(text: str) -> str:
        t = text.upper().strip()
        t = re.sub(r"\(([A-Z]{1,2})\)", r"-\1", t)          # HBR-F(L) -> HBR-F-L (a loyalty/special mark)
        t = re.sub(r"[^A-Z0-9\- ]", "", t)
        t = re.sub(r"\s*-\s*", "-", t)
        t = re.sub(r"\s+", "-", t)
        return t.strip("-")

    def lookup(self, token: str) -> tuple[Chassis, str, float] | None:
        """Return (chassis, variant suffix, confidence) for a scoreboard token, or None."""
        t = self.normalise(token)
        if len(t) < 2:
            return None
        for alias, key in self.aliases:
            if t.startswith(alias) and key in self.chassis:
                return self.chassis[key], t[len(alias):].lstrip("-") or "STD", 1.0
        prefix, _, suffix = t.partition("-")
        if prefix in self.chassis:
            return self.chassis[prefix], suffix, 1.0
        fixed = prefix.translate(self._FIX)
        if fixed in self.chassis:
            return self.chassis[fixed], suffix, 0.9
        # codes that legitimately hold digits (AS7, CN9, JR7, FS9, JM6, ON1) — the reverse swap too
        digital = prefix.translate(str.maketrans({"O": "0", "I": "1", "S": "5", "B": "8"}))
        for cand in (digital, digital[:2] + prefix[2:], prefix[:2] + digital[2:]):
            if cand in self.chassis:
                return self.chassis[cand], suffix, 0.85
        close = difflib.get_close_matches(prefix, self.codes, n=1, cutoff=0.75)
        if close and len(prefix) >= 3:
            return self.chassis[close[0]], suffix, 0.6
        return None


# a scoreboard token looks like CODE-SUFFIX; the suffix may carry dashes (AS7-D-DC, HBK-IIC-A)
# and a bracketed mark (HBR-F(L))
# the suffix must not swallow a health figure glued to it by OCR ("RVN-4X100%" -> RVN-4X)
_STOP = r"(?!\d{1,3}\s*%|DEAD|ALIVE|READY|CONNECT)"          # a health or a state word glued on by OCR ends the suffix
TOKEN = re.compile(r"\b([A-Z0-9]{2,4})\s*-\s*((?:" + _STOP + r"[A-Z0-9]){1,6}(?:\s*-\s*(?:" + _STOP + r"[A-Z0-9]){1,4}){0,2})(?:\s*\([A-Z]{1,2}\))?")


def find_tokens(line: str):
    """Every variant-shaped token in an OCR line, as (start, end, text)."""
    for m in TOKEN.finditer(line.upper()):
        yield m.start(), m.end(), m.group(0)
