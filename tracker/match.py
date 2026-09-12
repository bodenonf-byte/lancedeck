"""From OCR lines to a team picture.

Two screens carry what we need (both seen 2026-09-12):

  * the TAB SCOREBOARD — columns CMD, FACTION, PILOT NAME, 'MECH, STATUS, PING, MUTE; your
    team in lances ALPHA/BRAVO/CHARLIE with the variant code, the enemy block below with
    pilot names and STATUS only (their mechs are not revealed).  A row is the OCR lines on
    one baseline; the code names the mech; the STATUS word (ALIVE / DEAD) is exact; rows
    with a code are yours, rows with a status but no code are the enemy.
  * the in-play LANCE PANEL (top left) — "BRAVO LANCE", the four pilot names in a column,
    and beside them the four codes with either DEAD or a health percentage and a grid
    square ("RVN-4X DEAD", "LCT-PB 93% E5").  Names and codes pair by order.

  * the Q OVERLAY — hold Q and every mech in view carries a tag: health % and distance,
    the pilot's name, an optional title, then "CHASSIS CODE-VARIANT" ("KIT FOX KFX-D").
    Friend tags are blue, enemy tags red: the colour of the code's pixels says which side.

The scoreboard gives the whole team; the lance panel and the Q tags keep health and deaths
current while you play and fill in enemy mechs as they are seen.  `Roster.merge` joins them.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict

import numpy as np
from PIL import Image

from .mechdb import MechDB, find_tokens, CLASS_ORDER
from .ocr import Line

STATUS_ALIVE = re.compile(r"\bALIVE\b|\bNOT ?READY\b|\bREADY\b|\bCONNECTING\b")       # READY / NOT READY / CONNECTING: the drop screen, all alive
MODES = ["Conquest", "Assault", "Domination", "Skirmish", "Incursion", "Escort", "Siege", "Solaris"]
DROP_SCREEN = re.compile(r"DROP ?PREPARATION|YOUR ?ENEMY")
STATUS_DEAD = re.compile(r"\b(DEAD|DESTROYED|KIA|KILLED)\b")
STATUS_GONE = re.compile(r"\b(DISCONNECTED|DISCONNECT|LEFT)\b")
HEALTH = re.compile(r"(?<![\d%])(\d{1,3})\s*%")        # on text with the code already cut out
HEALTH_ANY = re.compile(r"(\d{1,4})\s*%")
from .mechdb import TOKEN as _TOKEN


def strip_codes(text: str) -> str:
    """The text with every variant token removed — so a health glued to a code that ends
    in a digit ("HSN-7D2100%") is read as 100, not lost inside 2100."""
    return _TOKEN.sub(" ", text.upper())
TAG = re.compile(r"\[[^\]]{1,8}\]")
LANCE_WORD = re.compile(r"\b(ALPHA|BRAVO|CHARLIE|DELTA)\b")
LANCE_HEADER = re.compile(r"\b(ALPHA|BRAVO|CHARLIE|DELTA)\s*LANCE\b")
HEADER = re.compile(r"\b(SCOREBOARD|PILOT NAME|MECH|STATUS|PING|MUTE|FACTION|CMD|YOUR TEAM|YOUR ENEMY|WELCOME)\b")
GRID = re.compile(r"\b[A-K](?:1[0-2]|[1-9])\b")
CHAT = re.compile(r"HAS ?KILLED|KILLED|DISCONNECTED|SPOTTED|SPOTTING|TYPE A ?MESSAGE|\bTEAM ?>|\bLANCE ?>|\bALL ?>|\[(TEAM|ALL|LANCE|GROUP|UNIT)\]|\bDAMAGED ?BY\b|DESTROYED BY|DAMAGE ?REPORT|CURRENT ?STATS|CAUSE ?OF ?DEATH|SPECTATE|YOU HAVE ?BEEN")
WEAPON_WORDS = re.compile(r"LASER|PPC|\bAC\b|\bUAC|\bLBX|LB ?\d|\bLRM|\bSRM|\bSSRM|\bATM|GAUSS|\bMG\b|MACHINE|FLAMER|NARC|TAG\b|AMS\b|DAMAGE|CRITICAL|HEAT|SHUTDOWN|OVERRIDE|SPOTTED|TARGET|KILLED|DESTROYED|ARMOR|ARMOUR|AMMO|JUMP ?JET|MASC|ECM|BAP|PULSE|MEDIUM|LARGE|SMALL|HEAVY|SNUB|MAGSHOT|WARNING|INCOMING|MISSILE|LOCK|CAPTUR|BASE|RESOURCE")
HUD_WORDS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "NORM", "KPH", "RNG", "CLR", "TRK", "FRONT", "REAR", "M/S", "MS",
             "SNUB-NOSE PPC", "MAGSHOT", "LANCE", "ALPHA", "BRAVO", "CHARLIE", "DELTA"}


def health_and_variant(tail_digits_text: str, variant: str) -> tuple[int | None, str]:
    """A health read off the text after the code.  OCR glues the variant's last digit to the
    figure ("CPLT-C3 93%" -> "C" + "393%"): anything over 100 hands its leading digits back to
    the variant — "393" is variant 3 + 93 %, "3100" is variant 3 + 100 %."""
    m = HEALTH_ANY.search(tail_digits_text)
    if not m:
        return None, variant
    s = m.group(1)
    v = int(s)
    if v <= 100:
        return v, variant
    if s.endswith("100"):
        return 100, variant + s[:-3]
    return int(s[-2:]), variant + s[:-2]


_KNOWN: list[str] = []
_PANEL: tuple | None = None


def set_panel_region(r) -> None:
    global _PANEL
    _PANEL = tuple(r) if r else None


def cfg_panel_region():
    return _PANEL


def set_known(names) -> None:
    """The roster's pilot names, so a Q tag's name pick can be checked against them."""
    global _KNOWN
    _KNOWN = [n for n in names if n and n not in ("?", "spotted")]


def cfg_known() -> list[str]:
    return _KNOWN


def name_score(a: str, b: str) -> float:
    import difflib
    na = re.sub(r"\s+", "", a.lower()); nb = re.sub(r"\s+", "", b.lower())
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if len(na) >= 5 and len(nb) >= 5 and (na in nb or nb in na):
        return 0.95
    return difflib.SequenceMatcher(None, na, nb).ratio()


def is_pilot_text(t: str) -> bool:
    u = t.strip().upper()
    if len(u) < 3 or u in HUD_WORDS:
        return False
    if re.fullmatch(r"[\d\s%.:M/-]+", u):
        return False
    return True
DIST = re.compile(r"(?<!\d)(\d{1,4})\s*M\b")


@dataclass
class Slot:
    pilot: str
    code: str | None        # chassis code, e.g. TBR; None when the screen hides the mech
    variant: str
    name: str
    tons: int
    cls: str
    faction: str
    pros: str
    cons: str
    alive: bool
    status: str             # ALIVE / DEAD / GONE / ?
    health: int | None      # percent, when the lance panel shows it
    lance: str              # ALPHA / BRAVO / CHARLIE / ""
    brightness: float
    conf: float
    y: int
    raw: str = ""           # the OCR row the read came from, for the sightings log
    score: int | None = None
    medal: int = 0          # 1 gold, 2 silver, 3 bronze — the end-of-match table's top three
    locked: bool = False    # the mech came from a named source and stays
    guess: bool = False     # the mech is a supposition from a recent game, not read this match
    loadout: list | None = None   # weapons read off the target info panel when this mech was locked


@dataclass
class TeamState:
    kind: str               # scoreboard / hud / none
    mine: list[Slot]
    enemy: list[Slot]
    source: str
    ts: float
    frame_w: int
    frame_h: int
    note: str = ""
    map: str = ""
    result: str = ""        # VICTORY / DEFEAT / "" once the end table has been seen
    mode: str = ""          # CONQUEST / ASSAULT / ... from the drop screen
    seen: list | None = None    # enemy mechs sighted but not yet tied to a pilot
    frozen: bool = False

    def as_dict(self):
        d = asdict(self)
        d["seen"] = d.get("seen") or []
        for side in ("mine", "enemy"):
            d[side].sort(key=lambda s: (CLASS_ORDER.get(s["cls"], 9), -s["tons"], not s["alive"], s["pilot"].lower()))
        return d


def row_brightness(img: Image.Image, y0: int, y1: int, x0: int, x1: int) -> float:
    x0 = max(0, x0); y0 = max(0, y0); x1 = min(img.width, x1); y1 = min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    band = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float32)
    return float(band.max(axis=2).mean() / 255.0)


def group_rows(lines: list[Line]) -> list[list[Line]]:
    """OCR lines sharing a baseline, each row sorted left to right."""
    if not lines:
        return []
    hs = sorted(l.h for l in lines)
    med_h = max(6, hs[len(hs) // 2])
    rows: list[list[Line]] = []
    for l in sorted(lines, key=lambda l: l.cy):
        if rows and abs(l.cy - sum(x.cy for x in rows[-1]) / len(rows[-1])) <= med_h * 0.6:
            rows[-1].append(l)
        else:
            rows.append([l])
    return [sorted(r, key=lambda l: l.x0) for r in rows]


def clean_name(text: str) -> str:
    """The pilot out of a scoreboard cell.  Icons, ranks, timers, scores and column labels
    land in the same OCR row as the name ("130 1 T1er5Ace", "C5 [CI] Noonan", "00:00 n
    Shado324", "YourEnemy MACE"): everything before the first token that carries three
    letters goes, so do trailing numbers, tags and lance words."""
    t = TAG.sub(" ", text)
    t = LANCE_WORD.sub(" ", t)
    t = re.sub(r"YOUR ?(TEAM|ENEMY)|\b(TEAM|LANCE)\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}:\d{2}\b", " ", t)
    t = re.sub(r"[|\u2022!\uff01\u300b\u300a\u53a6]", " ", t)
    toks = [x for x in re.split(r"\s+", t) if x]
    while toks and len(re.findall(r"[A-Za-z]", toks[0])) < 3:      # "Tw1st3dJ3st3r" has letters enough; "C5", "130", "n" do not
        toks.pop(0)
    while toks and re.fullmatch(r"[\d.,:%]+", toks[-1]):
        toks.pop()
    return " ".join(toks).strip(" -:")


NUM = re.compile(r"(?<![\d:%.])(\d{1,4})(?![\d:%])")
END_TABLE = re.compile(r"\b(VICTORY|DEFEAT|MATCH ?SCORE|TIE|DRAW|MISSION ?SUMMARY)\b")
TIME_TOKEN = re.compile(r"\b\d{1,2}:\d{2}\b")


def best_code(row: list[Line], db: MechDB):
    best = None
    for l in row:
        for s, e, tok in find_tokens(l.text):
            found = db.lookup(tok)
            if found and (best is None or found[2] * l.conf > best[3]):
                best = (found[0], found[1], l, found[2] * l.conf, s, e)
    return best


def unknown_slot(pilot: str, status: str, lance: str, br: float, y: int) -> Slot:
    return Slot(pilot, None, "", "unknown", 0, "Unknown", "", "", "", status != "DEAD", status, None, lance, br, 0.0, y)


def build(lines: list[Line], img: Image.Image, db: MechDB, cfg: dict, source: str) -> TeamState:
    my_name = (cfg.get("my_name") or "").strip().lower()
    band_x = cfg.get("row_band", [0.0, 1.0])
    bx0 = int(band_x[0] * img.width); bx1 = int(band_x[1] * img.width)
    rows = group_rows(lines)
    texts = [" ".join(l.text for l in r).upper() for r in rows]
    is_scoreboard = any(STATUS_ALIVE.search(t) or STATUS_DEAD.search(t) for t in texts) and any(HEADER.search(t) for t in texts)
    hud_header = [i for i, t in enumerate(texts) if LANCE_HEADER.search(t)]

    map_name = detect_map(texts)
    mode = ""
    for t in texts:
        if re.search(r"GAME ?MODE", t) or True:
            for m_ in MODES:
                if re.search(r"\b" + m_.upper() + r"\b", t) and (re.search(r"GAME ?MODE", t) or m_ != "Assault"):
                    mode = m_.upper(); break
        if mode:
            break
    drop = [i for i, t in enumerate(texts) if DROP_SCREEN.search(t)]
    enemy_hdr = [l for r in rows for l in r if re.search(r"YOUR ?ENEMY|^ENEMY$", l.text.upper())]
    team_hdr = [l for r in rows for l in r if re.search(r"YOUR ?TEAM", l.text.upper())]
    stacked = (bool(enemy_hdr) and min(l.x0 for l in enemy_hdr) < img.width * 0.45
               and not any(re.search(r"DROP ?PREPARATION", t) for t in texts))
    if drop and stacked and any(HEADER.search(t) for t in texts):
        # the in-match TAB: "Your Team" over the upper block (with mechs), "Your Enemy" beside
        # the lower block (names only) — the enemy label's height is the cut
        # the labels sit beside the MIDDLE of their blocks, so the cut is the widest gap between
        # consecutive rows in the span of the two labels — in the TAB your team is on top, on the
        # MISSION SUMMARY the enemy is; the block nearer the "Your Team" label is yours
        e_cy = min(l.cy for l in enemy_hdr)
        t_cy = min((l.cy for l in team_hdr), default=None)
        lo, hi = (min(e_cy, t_cy), max(e_cy, t_cy)) if t_cy is not None else (0, e_cy)
        cys = sorted({int(sum(l.cy for l in r) / len(r)) for r in rows
                      if lo - 1 <= sum(l.cy for l in r) / len(r) <= hi + 1})
        cut_y = e_cy - 6
        if len(cys) >= 2:
            gap, at = 0, None
            for a_, b_ in zip(cys, cys[1:]):
                if b_ - a_ > gap:
                    gap, at = b_ - a_, (a_ + b_) / 2
            if at is not None:
                cut_y = at
        # the mission summary labels both blocks' lances: the second ALPHA row opens the second
        # block — surer than a gap, which can be no wider than the gap between two lances
        alpha_rows = [r for r, t in zip(rows, texts) if t.strip().startswith("ALPHA")]
        if len(alpha_rows) >= 2:
            cut_y = min(l.y0 for l in alpha_rows[1]) - 3
        up = [l for l in lines if l.cy < cut_y]
        down = [l for l in lines if l.cy >= cut_y]
        ur = group_rows(up); ut = [" ".join(l.text for l in r).upper() for r in ur]
        dr = group_rows(down); dt = [" ".join(l.text for l in r).upper() for r in dr]
        scored_screen = any(END_TABLE.search(t) for t in texts) or sum(1 for t in texts if TIME_TOKEN.search(t)) >= 3
        a = scoreboard(ur, ut, img, db, my_name, bx0, bx1, source, scored_screen)
        b = scoreboard(dr, dt, img, db, my_name, bx0, bx1, source, scored_screen)
        upper = a.mine + a.enemy; lower = b.mine + b.enemy
        team_on_top = True
        if t_cy is not None:
            team_on_top = abs(t_cy - cut_y) < abs(e_cy - cut_y) and t_cy < e_cy or (t_cy < e_cy)
        mine, enemy = (upper, lower) if team_on_top else (lower, upper)
        if my_name and not any(my_name in s_.pilot.lower() for s_ in mine) and any(my_name in s_.pilot.lower() for s_ in enemy):
            mine, enemy = enemy, mine
        for s_ in enemy: s_.lance = ""
        mine = mine[:12]; enemy = enemy[:12]
        result = a.result or b.result
        # scores and medals are decided for the whole screen: the end table has a MATCH SCORE
        # column (or a result); the in-match TAB's first number is only the ping
        scored_screen = scored_screen or bool(result)
        for s_ in mine + enemy:
            s_.medal = 0
            if not scored_screen:
                s_.score = None
        if scored_screen:                                  # gold, silver, bronze on EACH team
            for side in (mine, enemy):
                for i, s_ in enumerate(sorted([s_ for s_ in side if s_.score is not None], key=lambda x: -x.score)[:3]):
                    s_.medal = i + 1
        st = TeamState("scoreboard", mine, enemy, source, time.time(), img.width, img.height,
                       ("end table" if scored_screen else "") if mine else "scoreboard seen but no mech codes read")
        st.result = result; st.map = map_name; st.mode = mode
        return st
    if drop and any(HEADER.search(t) for t in texts):
        # the loading screen: two tables side by side, yours left of the "YOUR ENEMY" header's x
        split_x = min(l.x0 for l in enemy_hdr) - 4 if enemy_hdr else int(img.width * 0.6)
        left = [l for l in lines if l.x1 <= split_x]; right = [l for l in lines if l.x0 >= split_x]
        lr = group_rows(left); lt = [" ".join(l.text for l in r).upper() for r in lr]
        rr = group_rows(right); rt = [" ".join(l.text for l in r).upper() for r in rr]
        a = scoreboard(lr, lt, img, db, my_name, bx0, bx1, source)
        b = scoreboard(rr, rt, img, db, my_name, bx0, bx1, source)
        mine = a.mine + [s for s in a.enemy if s.code]           # left table: everything is yours
        for s in a.enemy:
            if not s.code: mine.append(s)
        enemy = b.enemy + b.mine                                  # right table: everything is theirs (no mechs shown)
        for s in enemy: s.lance = ""
        if my_name and not any(my_name in s.pilot.lower() for s in mine) and any(my_name in s.pilot.lower() for s in enemy):
            mine, enemy = enemy, mine
        st = TeamState("scoreboard", mine, enemy, source, time.time(), img.width, img.height, "drop preparation")
        st.map = map_name; st.mode = mode
        return st
    death_screen = any(re.search(r"YOU HAVE ?BEEN ?DESTROYED|DAMAGE ?REPORT|CLICK ?TO ?SPECTATE", t) for t in texts)
    if death_screen and not is_scoreboard:
        # keep the lance panel (it stays up while dead) and nothing else from this frame
        keep = [r for r, t in zip(rows, texts) if not CHAT.search(t)]
        rows = keep; texts = [" ".join(l.text for l in r).upper() for r in rows]
        lines = [l for r in rows for l in r]
        hud_header = [i for i, t in enumerate(texts) if LANCE_HEADER.search(t)]
    if is_scoreboard and not drop:
        # the end-of-match table (and any two-tables screen): both teams at the same heights,
        # yours left, theirs right — an OCR row would glue one pilot of each into a single line
        splits = []
        for r in rows:
            marks = sorted([l for l in r if STATUS_ALIVE.search(l.text.upper()) or STATUS_DEAD.search(l.text.upper())
                            or STATUS_GONE.search(l.text.upper())], key=lambda l: l.x0)
            if len(marks) < 2 or marks[-1].x0 - marks[0].x1 < img.width * 0.2:
                continue
            # after the left status come the left table's numbers (score, time, kills, damage,
            # ping); the first cell that is not a number opens the right table — a pilot's name
            between = sorted([l for l in r if l.x0 >= marks[0].x1 and l.x1 <= marks[-1].x0], key=lambda l: l.x0)
            prev_x1 = marks[0].x1; at = None
            for l in between:
                if re.fullmatch(r"[\d\s:%.,\-]*", l.text.strip()):
                    prev_x1 = l.x1; continue
                at = (prev_x1 + l.x0) / 2; break
            if at is not None:
                splits.append(at)
        if len(splits) >= 3:
            split_x = sorted(splits)[len(splits) // 2]
            # a line goes to the side its centre is on: a left ping glued onto a right name
            # ("93 Suckatash Blitz") lands right and clean_name drops the number
            left = [l for l in lines if (l.x0 + l.x1) / 2 < split_x]; right = [l for l in lines if (l.x0 + l.x1) / 2 >= split_x]
            lr = group_rows(left); lt = [" ".join(l.text for l in r).upper() for r in lr]
            rr = group_rows(right); rt = [" ".join(l.text for l in r).upper() for r in rr]
            scored_screen = any(END_TABLE.search(t) for t in texts) or sum(1 for t in texts if TIME_TOKEN.search(t)) >= 3
            a = scoreboard(lr, lt, img, db, my_name, bx0, bx1, source, scored_screen)
            b = scoreboard(rr, rt, img, db, my_name, bx0, bx1, source, scored_screen)
            mine = a.mine + a.enemy; enemy = b.mine + b.enemy
            if my_name and not any(my_name in s.pilot.lower() for s in mine) and any(my_name in s.pilot.lower() for s in enemy):
                mine, enemy = enemy, mine
            result = a.result or b.result
            for s in mine + enemy:
                s.medal = 0; s.lance = ""
            for side in (mine, enemy):                       # gold, silver, bronze on EACH team
                for i, s in enumerate(sorted([s for s in side if s.score is not None], key=lambda s: -s.score)[:3]):
                    s.medal = i + 1
            st = TeamState("scoreboard", mine, enemy, source, time.time(), img.width, img.height, "end table")
            st.result = result; st.map = map_name; st.mode = mode
            return st
    if is_scoreboard:
        st = scoreboard(rows, texts, img, db, my_name, bx0, bx1, source)
    elif hud_header or any((HEALTH_ANY.search(strip_codes(t)) or DIST.search(strip_codes(t))) and best_code(r, db) for r, t in zip(rows, texts)):
        st = lance_panel(rows, texts, lines, img, db, hud_header, bx0, bx1, source)
    else:
        st = TeamState("none", [], [], source, time.time(), img.width, img.height, "nothing recognised")
    st.map = map_name; st.mode = mode
    return st


# MWO's maps, as the loading screen and the match-start banner print them
MAPS = ["Alpine Peaks", "Bearclaw", "Boreal Vault", "Canyon Network", "Caustic Valley", "Crimson Strait",
        "Emerald Taiga", "Forest Colony", "Free Worlds Coliseum", "Frozen City", "Grim Plexus", "Grim Portico",
        "Hellebore Springs", "Hibernal Rift", "HPG Manifold", "Mining Collective", "Polar Highlands",
        "River City", "Rubellite Oasis", "Solaris City", "Sulfurous Rift", "Terra Therma", "Tourmaline Desert",
        "Viridian Bog", "Vitric Forge", "Luthien", "Ceres Metal Scrapyard", "Mech Factory", "Boreal Reach", "Liao Jungle",
        "Ishiyama Caves", "Emerald Vale", "Hellebore Outpost", "Vitric Station", "Terra Therma Crucible", "Steiner Coliseum"]
_MAP_KEYS = [(re.sub(r"[^A-Z]", "", m.upper()), m) for m in MAPS]


def detect_map(texts: list[str]) -> str:
    """A map name anywhere on screen (the loading screen, the match-start banner)."""
    for t in texts:
        flat = re.sub(r"[^A-Z]", "", t.upper())
        if len(flat) < 6:
            continue
        for key, name in _MAP_KEYS:
            if key in flat:
                return name
    return ""


def row_numbers(row, after_x: int) -> list[int]:
    """The plain numbers on a row right of x (score, kills, assists, damage, ping)."""
    out = []
    for l in sorted(row, key=lambda l: l.x0):
        if l.x0 < after_x:
            continue
        t = strip_codes(l.text)
        if "%" in t:
            continue
        for m in NUM.finditer(t):
            out.append(int(m.group(1)))
    return out


def scoreboard(rows, texts, img, db, my_name, bx0, bx1, source, scored: bool | None = None) -> TeamState:
    slots: list[Slot] = []
    lance = ""
    result = ""
    for t in texts:
        m = END_TABLE.search(t)
        if m and m.group(1) in ("VICTORY", "DEFEAT", "TIE", "DRAW"):
            result = m.group(1)
    for row, up in zip(rows, texts):
        if CHAT.search(up):
            continue                                        # the chat / kill feed under the table
        m = LANCE_WORD.search(up)
        if m and not STATUS_ALIVE.search(up) and not STATUS_DEAD.search(up) and best_code(row, db) is None:
            lance = m.group(1); continue
        if m:
            lance = m.group(1)
        status = "?"
        if STATUS_DEAD.search(up): status = "DEAD"
        elif STATUS_ALIVE.search(up): status = "ALIVE"
        elif STATUS_GONE.search(up): status = "GONE"
        best = best_code(row, db)
        if best is None and status == "?":
            continue
        if HEADER.search(up) and best is None:
            continue
        cy = int(sum(l.cy for l in row) / len(row))
        y0 = min(l.y0 for l in row); y1 = max(l.y1 for l in row)
        br = row_brightness(img, y0, y1, bx0, bx1)
        if best is not None:
            ch, variant, code_line, conf, start, end = best
            before = [l.text for l in row if l.x1 <= code_line.x0 + 2] + [code_line.text[:start]]
            pilot = clean_name(" ".join(before))
            nums = row_numbers(row, code_line.x0 + 1)
            sl = Slot(pilot or "?", ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, ch.pros, ch.cons,
                      status != "DEAD", status, None, lance, br, conf, cy, up)
            sl.score = nums[0] if nums else None
            slots.append(sl)
        else:
            joined = " ".join(l.text for l in row)
            mm = STATUS_ALIVE.search(up) or STATUS_DEAD.search(up) or STATUS_GONE.search(up)
            head = joined[: mm.start()] if mm else joined
            unknown_code = ""
            toks = list(find_tokens(head))
            if toks:
                unknown_code = toks[-1][2].strip(); head = head[: toks[-1][0]]
            pilot = clean_name(head)
            if len(pilot) >= 2:
                sl = unknown_slot(pilot, status, lance, br, cy)
                sl.variant = unknown_code; sl.raw = up
                nums = row_numbers(row, max((l.x1 for l in row if mm and mm.group(0) in l.text.upper()), default=0) + 1) if mm else []
                sl.score = nums[0] if nums else None
                slots.append(sl)
    # which block is which
    slots.sort(key=lambda s: s.y)
    mine: list[Slot] = []; enemy: list[Slot] = []
    with_code = [s for s in slots if s.code]; without = [s for s in slots if not s.code]
    split_at = None
    if len(slots) >= 4:
        gaps = [(slots[i + 1].y - slots[i].y, i) for i in range(len(slots) - 1)]
        med = sorted(g for g, _ in gaps)[len(gaps) // 2]
        big = max(gaps)
        if big[0] > med * 1.8:
            split_at = big[1] + 1
    if split_at is not None:
        a, b = slots[:split_at], slots[split_at:]
        a_me = any(my_name and my_name in s.pilot.lower() for s in a)
        b_me = any(my_name and my_name in s.pilot.lower() for s in b)
        if b_me and not a_me:
            mine, enemy = b, a
        elif a_me or not b_me:
            # no name seen: the block that carries mechs is mine (the TAB), else the upper one
            if not any(s.code for s in a) and any(s.code for s in b):
                mine, enemy = b, a
            else:
                mine, enemy = a, b
        else:
            mine, enemy = b, a
    elif with_code and without and max(s.y for s in with_code) < min(s.y for s in without):
        mine, enemy = with_code, without                    # the in-match TAB: mechs above, names below
    else:
        mine, enemy = slots, []
        if my_name and not any(my_name in s.pilot.lower() for s in slots) and len(slots) <= 12 and without:
            mine, enemy = [], slots
    # a team is twelve.  A read that piles more than that on one side has missed the split:
    # in the in-match TAB the enemy never shows mechs, so pilots with a mech are mine and the
    # rest are theirs; failing that, cut at the largest vertical gap
    if len(mine) > 12 or len(enemy) > 12:
        pool = sorted(mine + enemy, key=lambda s: s.y)
        wc = [s for s in pool if s.code]; wo = [s for s in pool if not s.code]
        if 0 < len(wc) <= 12 and 0 < len(wo) <= 12:
            mine, enemy = wc, wo
        elif len(pool) >= 4:
            gaps = sorted(((pool[i + 1].y - pool[i].y, i) for i in range(len(pool) - 1)), reverse=True)
            cut = None
            for g, i in gaps:
                if 1 <= len(pool) - (i + 1) <= 12 and 1 <= i + 1 <= 12:
                    cut = i + 1; break
            if cut is not None:
                mine, enemy = pool[:cut], pool[cut:]
        if my_name and not any(my_name in s.pilot.lower() for s in mine) and any(my_name in s.pilot.lower() for s in enemy):
            mine, enemy = enemy, mine
        mine = mine[:12]; enemy = enemy[:12]
    has_score_column = any(re.search(r"\bSCORE\b", t) for t in texts) or sum(1 for t in texts if re.search(r"\b\d{1,2}:\d{2}\b", t)) >= 3
    if scored is not None:
        has_score_column = scored                          # decided by the caller for the whole screen
    if result or has_score_column:
        for side in (mine, enemy):                             # gold, silver, bronze on EACH team
            for i, s in enumerate(sorted([s for s in side if s.score is not None], key=lambda s: -s.score)[:3]):
                s.medal = i + 1
    else:
        for s in mine + enemy:
            s.score = None                                  # the in-match TAB's first number is the ping
    st = TeamState("scoreboard", mine, enemy, source, time.time(), img.width, img.height,
                   "" if mine else "scoreboard seen but no mech codes read")
    st.result = result
    return st


# a weapon line of the target info panel: "ER SML LASER", "LRM 15", "C-UAC/10", "GAUSS RIFLE"
WEAPON_LINE = re.compile(r"^(?:C-?\s*)?(?:(?:ER|LB|HVY|HEAVY|LIGHT|SNUB|X-?|MICRO|SML|SMALL|MED|MEDIUM|LRG|LARGE|PULSE|BINARY|STREAK|ULTRA|ROTARY|IMP|IMPROVED|ARTEMIS|CLAN|IS)[\s-]*)*"
                         r"(?:LASER|PPC|AC\s*/?\s*\d+|UAC\s*/?\s*\d+|RAC\s*/?\s*\d+|LB\s*\d+-?X?(?:\s*AC)?|GAUSS(?:\s*RIFLE)?|LRM\s*\d+|SRM\s*\d+|SSRM\s*\d+|MRM\s*\d+|ATM\s*\d+|"
                         r"MG|MACHINE\s*GUN|FLAMER|NARC|TAG|AMS|HAG\s*\d+|ROCKET\s*LAUNCHER\s*\d+|RL\s*\d+|PLASMA|MAGSHOT|CHEM\s*LASER)(?:\s*\+\s*ART(?:EMIS)?)?[\s\dX]*$")


def canon_weapon(t: str) -> str:
    """One spelling per weapon, whatever spaces OCR dropped: ERSMLLASER -> ER SML LASER."""
    k = re.sub(r"\s+", "", t.upper())
    k = re.sub(r"(?<=[A-Z0-9])(?=LASER|PPC|RIFLE|GUN|LAUNCHER|CANNON)", " ", k)
    k = re.sub(r"^(C-?|ER|IS|CLAN)(?=[A-Z])", r"\1 ", k)
    for _ in range(3):                                       # MEDPULSELASER -> MED PULSE LASER
        k = re.sub(r"(?<=[A-Z])(?=(?:SML|SMALL|MED|MEDIUM|LRG|LARGE|PULSE|HEAVY|HVY|LIGHT|MICRO|SNUB|STREAK|ULTRA|BINARY|ROTARY|CHEM|X-?)(?:[A-Z]|$))", " ", k)
    k = re.sub(r"(?<=[A-Z])(?=\d)", " ", k)                 # LRM15 -> LRM 15
    k = re.sub(r"\s+", " ", k).replace("C- ", "C-").strip()
    return k


def target_panel(lines: list[Line], img: Image.Image, db: MechDB) -> TeamState:
    """The top-right panel while a mech is locked: its weapons listed on the left, the paper
    doll in the middle, the chassis and variant under it ("FLEA FLE-20").  Returns one slot of
    kind "target" carrying code, variant and the loadout, or nothing."""
    none = TeamState("none", [], [], "target", time.time(), img.width, img.height, "")
    hit = None
    for l in lines:
        for _, _, tok in find_tokens(l.text):
            h = db.lookup(tok)
            if h and h[2] >= 0.85 and (hit is None or h[2] > hit[2]):
                hit = h
    if hit is None:
        return none
    weapons = []
    for l in sorted(lines, key=lambda l: (l.y0, l.x0)):
        t = re.sub(r"\s+", " ", l.text.upper().strip())
        toks = list(find_tokens(t))
        if len(t) < 2 or (toks and db.lookup(toks[0][2])):
            continue                                     # the variant line, not a weapon
        if t in HUD_WORDS or t in ("FRONT", "REAR", "L", "R", "LL", "RR", "C"):
            continue
        if WEAPON_LINE.match(t):
            weapons.append(canon_weapon(t))
    if not weapons:
        return none
    ch, variant, conf = hit
    sl = Slot("?", ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, ch.pros, ch.cons, True, "LOCKED", None, "", 0, conf, 0,
              " | ".join(weapons))
    sl.loadout = weapons
    return TeamState("target", [], [sl], "target", time.time(), img.width, img.height, "")


def lance_panel(rows, texts, lines, img, db, hud_header, bx0, bx1, source) -> TeamState:
    """The four lance mates: names in the left column, codes with DEAD / health beside them,
    paired by order."""
    lance = ""
    if hud_header:
        lance = LANCE_HEADER.search(texts[hud_header[0]]).group(1)
    chassis_names = {c.name.upper() for c in db.chassis.values()}
    tag_rows = set()
    codes = []          # (y, x, slot)
    pr = cfg_panel_region()
    def in_panel(l):
        return pr is not None and pr[0] * img.width <= (l.x0 + l.x1) / 2 <= pr[2] * img.width and pr[1] * img.height <= l.cy <= pr[3] * img.height
    for ri, (row, up) in enumerate(zip(rows, texts)):
        if best_code(row, db) is None:
            continue
        named = any(n in up for n in chassis_names if len(n) > 3)
        if named or DIST.search(strip_codes(up)):
            tag_rows.add(ri); continue                     # a Q-overlay tag, read below
        cy = int(sum(l.cy for l in row) / len(row))
        y0 = min(l.y0 for l in row); y1 = max(l.y1 for l in row)
        br = row_brightness(img, y0, y1, bx0, bx1)
        # every code on the row, each with the text that follows it up to the next code
        pieces = []
        for l in sorted(row, key=lambda l: l.x0):
            toks = list(find_tokens(l.text))
            for i, (st_, en_, tok) in enumerate(toks):
                nxt = toks[i + 1][0] if i + 1 < len(toks) else len(l.text)
                pieces.append((l, tok, l.text[en_:nxt], i == len(toks) - 1))
        for idx_p, (l, tok, tail_txt, last) in enumerate(pieces):
            found = db.lookup(tok)
            if not found or found[2] < 0.85:
                continue
            ch, variant, c0 = found
            tail = tail_txt
            if last:
                tail += " " + " ".join(o.text for o in row if o is not l and o.x0 >= l.x1 - 2 and not list(find_tokens(o.text)))
            tail = strip_codes(tail)
            health, variant = health_and_variant(tail, variant)
            status = "DEAD" if STATUS_DEAD.search(tail) else ("ALIVE" if health is not None else "?")
            if status == "?" and health is None:
                if in_panel(l):
                    status = "ALIVE"                          # inside the panel a code is a mate even when its state failed to read
                else:
                    continue                                  # a code without a state word elsewhere is not the panel
            codes.append((cy, l.x0, Slot("?", ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, ch.pros, ch.cons,
                                          status != "DEAD", status, health, lance, br, c0 * l.conf, cy, up)))
    friends, foes = q_tags(rows, texts, tag_rows, img, db)
    if not codes:
        if friends or foes:
            return TeamState("hud", friends, foes, source, time.time(), img.width, img.height, "")
        return TeamState("none", [], [], source, time.time(), img.width, img.height, "lance panel: no codes")
    codes.sort(key=lambda c: c[0])
    code_x = min(c[1] for c in codes)
    header_y = sum(l.cy for l in rows[hud_header[0]]) / len(rows[hud_header[0]]) if hud_header else codes[0][0] - 60
    # the names: every OCR line left of the code column, below the header and not further
    # down than the last code plus a row — in reading order, because the name column runs
    # half a row above the code column and a baseline grouping pairs them wrong
    names = []
    for l in sorted(lines, key=lambda l: l.cy):
        if l.cy <= header_y or l.cy > codes[-1][0] + 40 or l.x1 > code_x - 4:
            continue
        up = l.text.upper()
        if LANCE_HEADER.search(up) or list(find_tokens(l.text)) or HEALTH.search(up) or STATUS_DEAD.search(up):
            continue
        pilot = GRID.sub("", clean_name(l.text)).strip()
        flat = re.sub(r"[^A-Z]", "", l.text.upper())
        if any(flat.startswith(w) for w in ("ALPHA", "BRAVO", "CHARLIE", "DELTA")) or pilot.upper() in HUD_WORDS:
            continue
        if len(pilot) >= 2:
            names.append((l.cy, pilot))
    names.sort()
    for i, (_, _, slot) in enumerate(codes):
        if i < len(names):
            slot.pilot = names[i][1]
    note = "" if len(names) == len(codes) else f"lance panel: {len(codes)} mechs, {len(names)} names read"
    # enemy sightings: a code on the HUD that is not a lance mate — the target readout when
    # you lock an enemy. If a pilot name sits on a neighbouring row of that readout it is
    # taken; otherwise the sighting is filed as "spotted" and the roster matches it later.
    seen_rows = {id(c[2]) for c in codes}
    lance_ys = [c[0] for c in codes]
    enemy: list[Slot] = []
    for idx, (row, up) in enumerate(zip(rows, texts)):
        best = best_code(row, db)
        if best is None or best[3] < 0.85 or CHAT.search(up) or HEALTH_ANY.search(strip_codes(up)) or STATUS_DEAD.search(up) or idx in tag_rows:
            continue
        if in_panel(best[2]):
            continue                                          # the lance panel's corner is never an enemy sighting
        cy = sum(l.cy for l in row) / len(row)
        if any(abs(cy - y) < 4 for y in lance_ys):
            continue
        ch, variant, code_line, conf, start, end = best
        pilot = "spotted"
        chassis_names = {c.name.upper() for c in db.chassis.values()}
        for j in (idx - 1, idx - 2, idx + 1, idx + 2):
            if 0 <= j < len(rows):
                t = clean_name(" ".join(l.text for l in rows[j]))
                t = GRID.sub("", t).strip()
                if (is_pilot_text(t) and len(t) <= 24 and not best_code(rows[j], db) and not re.search(r"\d{2,}", t)
                        and not HEADER.search(t.upper()) and not CHAT.search(t.upper()) and not WEAPON_WORDS.search(t.upper()) and t.upper() not in chassis_names
                        and not any(abs(sum(l.cy for l in rows[j]) / len(rows[j]) - y) < 4 for y in lance_ys)):
                    pilot = t; break
        known = cfg_known()
        if known and pilot != "spotted":
            best_k = max(((name_score(pilot, k), k) for k in known), default=(0.0, None))
            pilot = best_k[1] if best_k[0] >= 0.8 else "spotted"
        enemy.append(Slot(pilot, ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, ch.pros, ch.cons,
                          True, "SEEN", None, "", 0.0, conf, int(cy), up))
    return TeamState("hud", [c[2] for c in codes] + friends, enemy + foes, source, time.time(), img.width, img.height, note)


def text_side(img: Image.Image, l: Line) -> str:
    """friend / enemy / ? from the colour of a text box's bright pixels (blue-cyan vs red)."""
    x0, y0, x1, y1 = max(0, l.x0), max(0, l.y0), min(img.width, l.x1), min(img.height, l.y1)
    if x1 <= x0 or y1 <= y0:
        return "?"
    a = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float32)
    mx = a.max(axis=2); mn = a.min(axis=2)
    sat = (mx - mn) / (mx + 1e-6)
    sel = (mx > 120) & (sat > 0.3)
    if sel.sum() < 12:
        return "?"
    r, g, b = a[sel].mean(axis=0)
    if r > 1.25 * max(g, b):
        return "enemy"
    if max(g, b) > 1.2 * r:
        return "friend"
    return "?"


def q_tags(rows, texts, tag_rows, img, db):
    """The Q-overlay tags: for a code row, the block of lines stacked above it (same x
    range, within three rows) holds health, distance, the pilot and maybe a title; the
    pilot is the first line of the block that is neither a number nor a chassis name."""
    chassis_names = {c.name.upper() for c in db.chassis.values()}
    friends: list[Slot] = []; foes: list[Slot] = []
    for ri in sorted(tag_rows):
        row = rows[ri]; up = texts[ri]
        if CHAT.search(up):
            continue
        best = best_code(row, db)
        if best is None or best[3] < 0.85:                    # a fuzzy chassis guess never makes a sighting
            continue
        ch, variant, code_line, conf, start, end = best
        block = [(sum(l.cy for l in r) / len(r), t, r) for r, t in zip(rows, texts)]
        cy = sum(l.cy for l in row) / len(row)
        rh = max(8, code_line.h)
        above = [(y, t, r) for y, t, r in block if cy - 3.6 * rh <= y < cy - 0.4 * rh
                 and any(l.x1 > code_line.x0 - 2 * rh and l.x0 < code_line.x1 + 2 * rh for l in r)]
        joined = strip_codes(up + " " + " ".join(t for _, t, _ in above))
        dm = DIST.search(joined)
        health, variant = health_and_variant(joined, variant)
        if health is None and dm is None:
            continue
        dist = int(dm.group(1)) if dm else None
        pilot = "spotted"
        cands = []
        for y, t, r in above:
            if cy - y > 2.6 * rh:
                continue
            for l in r:
                ov = min(l.x1, code_line.x1) - max(l.x0, code_line.x0)
                if ov < 0.4 * min(l.x1 - l.x0, code_line.x1 - code_line.x0):
                    continue
                if list(find_tokens(l.text)) or HEALTH_ANY.search(l.text) or DIST.search(l.text.upper()):
                    continue
                cand = GRID.sub("", clean_name(l.text)).strip()
                if is_pilot_text(cand) and cand.upper() not in chassis_names and not WEAPON_WORDS.search(cand.upper()) and not CHAT.search(cand.upper()):
                    cands.append((y, cand))
        known = cfg_known()
        if cands and known:
            best_k = (0.0, None)
            for _, cand in cands:
                for k in known:
                    sc = name_score(cand, k)
                    if sc > best_k[0]:
                        best_k = (sc, k)
            if best_k[0] >= 0.8:
                pilot = best_k[1]
        elif cands and not known:
            cands.sort()
            pilot = cands[0][1]
        side = text_side(img, code_line)
        status = "DEAD" if STATUS_DEAD.search(joined) else ("ALIVE" if health is not None else "SEEN")
        slot = Slot(pilot, ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, ch.pros, ch.cons,
                    status != "DEAD", status, health, "", 0.0, conf, int(cy), up)
        # blue is a friend; red, and the HUD's amber target readout, are enemy sightings
        (friends if side == "friend" else foes).append(slot)
    return friends, foes
