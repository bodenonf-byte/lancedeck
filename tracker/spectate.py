"""The caster's view of a competitive match, and the picture it builds up.

When a match is watched from the spectator (caster) client the screen is not the player's
HUD: both teams sit in two tables, left and right, one row per pilot — Health, Player Name,
Mech Type, K, A on the left; A, K, Mech Type, Player Name, Health mirrored on the right —
under the team's name and tag.  The top carries the series score ("EXD8 - 0" / "GIFT - 0"),
the match score with the clock between ("213  12:18  137") and, on Conquest, the five
capture points coloured by their owner.  When the caster highlights a pilot, a box at the
bottom right names them, their health, their mech and their weapons ("6 x C-ER MED LASER").

`build` turns one frame's OCR lines into a CompFrame; `CompRoster.merge` keeps the match
across frames: health, kills, assists and deaths follow the tables, a loadout read off the
highlight box sticks to its pilot, and a new match (different teams or a new roster)
replaces the old one.  Everything the page shows comes from `CompRoster.as_dict`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict

import numpy as np
from PIL import Image

from .match import group_rows, best_code, clean_name, canon_weapon, WEAPON_LINE, HEALTH_ANY, name_score
from .mechdb import MechDB, find_tokens, CLASS_ORDER
from .ocr import Line
from . import weapons as weapondb

HEAD_HEALTH = re.compile(r"^\W*HEALTH\W*$", re.I)
HEAD_NAME = re.compile(r"PLAYER\s*NAME", re.I)
HEAD_MECH = re.compile(r"MECH\s*TYPE", re.I)
SERIES = re.compile(r"^\s*([A-Z0-9]{2,8})\s*[-–]\s*([0-9O]{1,2})\s*$")
CLOCK = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
HIGHLIGHT = re.compile(r"HIGHLIGHT\s*:?\s*(.*)", re.I)
HEALTH_LABEL = re.compile(r"HEALTH\s*:?\s*(\d{1,3})?\s*%?", re.I)
COUNT_X = re.compile(r"^\s*(\d{1,2})\s*[x×X]\s*(.+?)\s*$")
CAP_NAMES = ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA", "ETA", "THETA", "IOTA", "KAPPA", "LAMBDA", "SIGMA", "OMEGA")
SMALL_INT = re.compile(r"^\d{1,2}$")
GLUED_CODE = re.compile(r"([A-Z]{2,})(-[A-Z0-9()\-]{1,12})$")


@dataclass
class CompPilot:
    pilot: str
    code: str | None
    variant: str
    name: str
    tons: int
    cls: str
    faction: str
    health: int | None
    alive: bool
    kills: int | None
    assists: int | None
    y: int = 0
    conf: float = 0.0
    loadout: list | None = None
    votes: dict = field(default_factory=dict)      # every spelling this row's name was read as


@dataclass
class CompTeam:
    name: str = ""
    tag: str = ""
    series: int | None = None
    score: int | None = None
    pilots: list = field(default_factory=list)


@dataclass
class CompFrame:
    kind: str                       # "comp" when the tables were read, "highlight" when only the box was, "none"
    left: CompTeam
    right: CompTeam
    clock: str = ""
    caps: list = field(default_factory=list)       # [{"name": "GAMMA", "side": "left"|"right"|""}]
    highlight: dict | None = None                  # {"pilot", "health", "code", "variant", "name", "loadout": [...]}
    ts: float = 0.0
    frame_w: int = 0
    frame_h: int = 0


def _side_of_colour(img: Image.Image, l: Line) -> str:
    """Which team a coloured word belongs to: the game paints the left team's things blue
    and the right team's red (the tables' headers are blue on the left, red on the right)."""
    x0 = max(0, l.x0); y0 = max(0, l.y0); x1 = min(img.width, l.x1); y1 = min(img.height, l.y1)
    if x1 <= x0 or y1 <= y0:
        return ""
    a = np.asarray(img.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.int32)
    bright = a.max(axis=2) > 120
    if bright.sum() < 8:
        return ""
    px = a[bright]
    r, g, b = px[:, 0].mean(), px[:, 1].mean(), px[:, 2].mean()
    if b > r + 40 and b >= g:
        return "left"
    if r > b + 40 and r >= g:
        return "right"
    return ""


def _int(t: str) -> int | None:
    t = t.strip().replace("O", "0").replace("o", "0")
    return int(t) if SMALL_INT.match(t) else None


def _read_table(rows: list[list[Line]], texts: list[str], x_lo: int, x_hi: int, y_top: int, y_bot: int,
                db: MechDB, left: bool) -> list[CompPilot]:
    """The rows of one team's table between the header and the box under it."""
    out: list[CompPilot] = []
    for row, t in zip(rows, texts):
        cy = sum(l.cy for l in row) / len(row)
        if not (y_top < cy < y_bot):
            continue
        cells = [l for l in row if x_lo <= l.x0 and l.x1 <= x_hi]
        if len(cells) < 2:
            continue
        b = best_code(cells, db)
        if not b:
            continue
        ch, variant, code_line, conf, _, _ = b
        health = None; alive = True
        name_parts = []; ints = []
        for l in cells:
            if l is code_line:
                continue
            tx = l.text.strip()
            m = HEALTH_ANY.search(tx)
            if m and (l.x1 < code_line.x0 if left else l.x0 > code_line.x1):
                health = min(100, int(m.group(1)))
                rest = HEALTH_ANY.sub(" ", tx).strip()          # "98%NeirSolon": the name glued to the health
                if rest and len(re.findall(r"[A-Za-z]", rest)) >= 3:
                    name_parts.append(rest)
                continue
            if re.fullmatch(r"\s*(DEAD|DESTROYED|KIA)\s*", tx, re.I):
                alive = False; continue
            v = _int(tx)
            if v is not None:
                ints.append((l.x0, v)); continue
            if len(re.findall(r"[A-Za-z]", tx)) >= 2:
                name_parts.append(tx)
        pilot = clean_name(" ".join(name_parts)) if name_parts else ""
        if not pilot:
            continue
        # K and A: the two small numbers beyond the code (left table: K then A; right: A then K before the name)
        kills = assists = None
        if left:
            after = sorted((x, v) for x, v in ints if x > code_line.x1)
            if len(after) >= 2:
                kills, assists = after[0][1], after[1][1]
            elif len(after) == 1:
                kills = after[0][1]
        else:
            before = sorted((x, v) for x, v in ints if x < code_line.x0)
            if len(before) >= 2:
                assists, kills = before[0][1], before[1][1]
            elif len(before) == 1:
                kills = before[0][1]
        if health == 0:
            alive = False
        out.append(CompPilot(pilot, ch.code, variant, ch.name, ch.tons, ch.cls, ch.faction, health, alive, kills, assists, int(cy), conf))
    return out


def _highlight(lines: list[Line], img: Image.Image, db: MechDB) -> dict | None:
    hl = next((l for l in lines if HIGHLIGHT.search(l.text)), None)
    if hl is None:
        return None
    m = HIGHLIGHT.search(hl.text)
    pilot = clean_name(m.group(1)) if m else ""
    # the box: below the HIGHLIGHT line, its left edge roughly the line's, down to the bottom
    box = [l for l in lines if l.cy > hl.cy and l.x0 >= hl.x0 - img.width * 0.05 and l.x0 < hl.x0 + img.width * 0.14]
    if not pilot:
        # the name may sit on the next line
        cand = next((l for l in box if len(l.text) > 2 and not HEALTH_LABEL.match(l.text)), None)
        if cand:
            pilot = clean_name(cand.text); box = [l for l in box if l is not cand]
    health = None; code = variant = name = ""; tons = 0; cls = ""; loadout: list[str] = []
    right_edge = hl.x0 + img.width * 0.16                     # weapons are the box's left column
    for l in sorted(box, key=lambda l: l.cy):
        t = l.text.strip()
        hm = HEALTH_LABEL.match(t)
        if hm:
            if hm.group(1):
                health = int(hm.group(1))
            continue
        if health is None and re.fullmatch(r"\d{1,3}\s*%", t):
            health = int(re.match(r"\d+", t).group(0)); continue
        # the mech line: "EXECUTIONER EXE-M", often glued by OCR ("EXECUTIONEREXE-M")
        toks = [tok for _, _, tok in find_tokens(t)]
        gm = GLUED_CODE.search(t.upper().replace(" ", ""))
        if gm:
            head, tail = gm.group(1), gm.group(2)
            toks.extend(head[-n:] + tail for n in (2, 3, 4) if len(head) >= n)
        hit = None
        for tok in toks:
            h = db.lookup(tok)
            if h and h[2] >= 0.85 and (hit is None or h[2] > hit[2]):
                hit = h
        if hit and not code:
            code, variant, name, tons, cls = hit[0].code, hit[1], hit[0].name, hit[0].tons, hit[0].cls
            continue
        if l.x0 > right_edge:
            continue
        cm = COUNT_X.match(t)
        n, w = (int(cm.group(1)), cm.group(2)) if cm else (1, t)
        wu = re.sub(r"\s+", " ", w.upper())
        if WEAPON_LINE.match(wu) or weapondb.norm(wu):
            loadout.extend([canon_weapon(wu)] * max(1, min(n, 12)))
    if not pilot and not code:
        return None
    return {"pilot": pilot, "health": health, "code": code or None, "variant": variant, "name": name, "tons": tons, "cls": cls, "loadout": loadout}


def build(lines: list[Line], img: Image.Image, db: MechDB) -> CompFrame:
    """One frame of the caster's client, or kind "none"."""
    W, H = img.width, img.height
    none = CompFrame("none", CompTeam(), CompTeam(), ts=time.time(), frame_w=W, frame_h=H)
    heads_h = [l for l in lines if HEAD_HEALTH.match(l.text)]
    heads_n = [l for l in lines if HEAD_NAME.search(l.text)]
    heads_m = [l for l in lines if HEAD_MECH.search(l.text)]
    hi = _highlight(lines, img, db)
    if len(heads_m) < 2 or (len(heads_h) + len(heads_n)) < 2:
        if hi:
            return CompFrame("highlight", CompTeam(), CompTeam(), highlight=hi, ts=time.time(), frame_w=W, frame_h=H)
        return none
    lm = min(heads_m, key=lambda l: l.x0); rm = max(heads_m, key=lambda l: l.x0)
    if lm.x0 > W * 0.45 or rm.x0 < W * 0.55 or abs(lm.cy - rm.cy) > lm.h * 2:
        if hi:
            return CompFrame("highlight", CompTeam(), CompTeam(), highlight=hi, ts=time.time(), frame_w=W, frame_h=H)
        return none
    head_y = (lm.cy + rm.cy) / 2
    rows = group_rows(lines)
    texts = [" ".join(l.text for l in r).upper() for r in rows]
    pitch = max(18, int(lm.h * 1.4))
    y_bot = head_y + pitch * 13.5                     # twelve rows at most, plus slack
    left = _read_table(rows, texts, 0, int(W * 0.45), head_y + lm.h * 0.5, y_bot, db, True)
    right = _read_table(rows, texts, int(W * 0.55), W, head_y + rm.h * 0.5, y_bot, db, False)
    if not left and not right:
        return none
    lt = CompTeam(pilots=left); rt = CompTeam(pilots=right)
    # team names: the line just above each header, on its side; a short tag sits at the far edge
    for team, side_lo, side_hi in ((lt, 0, W * 0.30), (rt, W * 0.70, W)):
        above = [l for l in lines if side_lo <= l.x0 and l.x1 <= side_hi and head_y - lm.h * 3.2 < l.cy < head_y - lm.h * 0.6
                 and len(l.text.strip()) >= 2 and l.text.strip().upper() not in CAP_NAMES
                 and not HEAD_MECH.search(l.text) and not HEAD_NAME.search(l.text) and not HEAD_HEALTH.match(l.text)]
        if above:
            longest = max(above, key=lambda l: len(l.text))
            team.name = re.sub(r"\s+", " ", longest.text.strip())
            short = [l for l in above if l is not longest and len(l.text.strip()) <= 6]
            if short:
                team.tag = short[0].text.strip().upper()
    # the series score, big, at the very top of each side
    for l in lines:
        if l.cy < head_y - lm.h * 1.5 and l.h >= lm.h * 1.5:
            m = SERIES.match(l.text.upper().replace(" ", ""))
            if m:
                team = lt if l.x0 < W * 0.5 else rt
                team.series = int(m.group(2).replace("O", "0"))
                team.tag = m.group(1)                  # the series banner spells the tag best
    # the clock and the two match scores beside it
    clock = next((l for l in lines if CLOCK.match(l.text) and abs(l.cy - (head_y - lm.h * 2.5)) < H * 0.12 and W * 0.35 < l.x0 < W * 0.65), None)
    fr = CompFrame("comp", lt, rt, ts=time.time(), frame_w=W, frame_h=H, highlight=hi)
    if clock:
        fr.clock = clock.text.strip()
        nums = [l for l in lines if re.fullmatch(r"\d{1,4}", l.text.strip()) and abs(l.cy - clock.cy) < clock.h * 1.2 and abs(l.x0 - clock.x0) < W * 0.15]
        ls_ = [l for l in nums if l.x1 <= clock.x0]; rs_ = [l for l in nums if l.x0 >= clock.x1]
        if ls_: lt.score = int(max(ls_, key=lambda l: l.x1).text)
        if rs_: rt.score = int(min(rs_, key=lambda l: l.x0).text)
    # capture points, coloured by owner
    for l in lines:
        t = l.text.strip().upper()
        if t in CAP_NAMES and l.cy < head_y and W * 0.25 < l.x0 < W * 0.75:
            fr.caps.append({"name": t, "side": _side_of_colour(img, l)})
    fr.caps.sort(key=lambda c: c["name"])
    return fr


# ── the match across frames ──────────────────────────────────────────────────────────────
def _row_pitch(pilots) -> float:
    """How far apart the rows of a team table sit, in pixels."""
    ys = sorted(p.y for p in pilots if p.y)
    gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 2]
    if not gaps:
        return 24.0
    gaps.sort()
    return max(10.0, gaps[len(gaps) // 2])


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class CompRoster:
    def __init__(self):
        self.clear()

    def clear(self):
        self.left = CompTeam(); self.right = CompTeam()
        self.clock = ""; self.caps = []; self.highlight = None
        self.started = 0.0; self.updated = 0.0; self.frames = 0
        self.highlight_ts = 0.0
        self.history: list[dict] = []          # the score as the clock runs down

    # ── how the points are going ─────────────────────────────────────────────────────────
    # On the modes that score (Conquest and the like) the interesting thing is not the two
    # numbers but their slope: who is gaining, how fast, and where that lands when the clock
    # reaches zero.  The capture points drive it, so they are kept alongside.
    HISTORY_MAX = 600

    @staticmethod
    def _seconds(clock: str) -> int | None:
        m = CLOCK.match(clock or "")
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None

    def _note_progress(self):
        left, right = self.left.score, self.right.score
        if left is None and right is None:
            return
        secs = self._seconds(self.clock)
        caps = (sum(1 for c in self.caps if c.get("side") == "left"),
                sum(1 for c in self.caps if c.get("side") == "right"))
        last = self.history[-1] if self.history else None
        if last and last["left"] == left and last["right"] == right and last["caps"] == list(caps):
            return                                   # nothing moved
        if last and secs is not None and last["left_s"] is not None and secs > last["left_s"]:
            self.history.clear()                     # the clock went back up: a new match
        self.history.append({"ts": self.updated, "left_s": secs, "left": left, "right": right, "caps": list(caps)})
        if len(self.history) > self.HISTORY_MAX:
            del self.history[:len(self.history) - self.HISTORY_MAX]

    def _progress(self) -> dict | None:
        """Points per minute over the recent past, and where the clock running out lands."""
        pts = [h for h in self.history if h["left"] is not None or h["right"] is not None]
        if len(pts) < 2:
            return None
        now = pts[-1]
        secs = now["left_s"]
        # look back about two minutes of match time, or to the start of what we have
        back = next((h for h in reversed(pts[:-1])
                     if h["left_s"] is not None and secs is not None and h["left_s"] - secs >= 90), pts[0])
        rate = {"left": None, "right": None}
        if back["left_s"] is not None and secs is not None and back["left_s"] > secs:
            mins = (back["left_s"] - secs) / 60.0
            for side in ("left", "right"):
                if now[side] is not None and back[side] is not None:
                    rate[side] = round((now[side] - back[side]) / mins, 1)
        projected = {"left": None, "right": None}
        if secs:
            for side in ("left", "right"):
                if now[side] is not None and rate[side] is not None:
                    projected[side] = int(round(now[side] + rate[side] * secs / 60.0))
        return {"points": [{"t": h["left_s"], "l": h["left"], "r": h["right"]} for h in pts[-120:]],
                "rate": rate, "projected": projected, "caps": {"left": now["caps"][0], "right": now["caps"][1]},
                "lead": (now["left"] - now["right"]) if (now["left"] is not None and now["right"] is not None) else None,
                "seconds_left": secs}

    def _find(self, pilot: str):
        k = _key(pilot)
        best = None; best_s = 0.0
        for side in (self.left, self.right):
            for p in side.pilots:
                s = 1.0 if _key(p.pilot) == k else name_score(p.pilot, pilot)
                if s > best_s:
                    best, best_s = p, s
        return best if best_s >= 0.72 else None

    def _same_match(self, fr: CompFrame) -> bool:
        """Is this still the match we have been watching?

        A series is the same sixteen people playing map after map, and they SWAP SIDES between
        maps — so "are these the same pilots?" says yes to every map of the series, and the new
        map's rows then land on the old map's pilots, giving a board where everyone is on the
        wrong team (2026-09-28: FunkyCat shown on 228th IBR while the stream had them on TEAM 2,
        with last map's mechs and this map's health).  Each side is therefore judged on its own,
        and a clock that has gone back up means the next map has started."""
        have = {_key(p.pilot) for p in self.left.pilots + self.right.pilots}
        seen = {_key(p.pilot) for p in fr.left.pilots + fr.right.pilots}
        if not have or not seen:
            return not have
        now, before = self._seconds(fr.clock), self._seconds(self.clock)
        if now is not None and before is not None and now > before + 60:
            return False
        for mine, theirs in ((self.left, fr.left), (self.right, fr.right)):
            h = {_key(p.pilot) for p in mine.pilots}
            s = {_key(p.pilot) for p in theirs.pilots}
            if h and s and len(h & s) < max(1, len(s) // 2):
                return False                      # this side is not the side it was
        common = len(have & seen)
        return common >= max(2, len(seen) // 2)

    def merge(self, fr: CompFrame) -> bool:
        """Fold a frame in.  True when anything changed."""
        changed = False
        if fr.kind == "comp":
            if not self._same_match(fr):
                self.clear(); self.started = fr.ts; changed = True
            if not self.started:
                self.started = fr.ts
            for mine, theirs in ((self.left, fr.left), (self.right, fr.right)):
                if theirs.name and theirs.name != mine.name: mine.name = theirs.name; changed = True
                if theirs.tag and theirs.tag != mine.tag: mine.tag = theirs.tag; changed = True
                if theirs.series is not None and theirs.series != mine.series: mine.series = theirs.series; changed = True
                if theirs.score is not None and theirs.score != mine.score: mine.score = theirs.score; changed = True
                pitch = _row_pitch(theirs.pilots)
                for p in theirs.pilots:
                    # THE ROW IS THE PILOT.  A team table has one line each and they do not
                    # move, so position decides and the letters only vote on the spelling: a
                    # name read two ways ("Lizzee" / "uzzee", both at y 374) once made a ninth
                    # pilot on an eight-strong team, and two pilots whose names merely look
                    # alike used to collapse into one.  Name matching is the fallback, for a
                    # frame where the row could not be placed.
                    cur = next((q for q in mine.pilots if _key(q.pilot) == _key(p.pilot)), None)
                    if cur is None and p.y:
                        cur = next((q for q in mine.pilots if q.y and abs(q.y - p.y) <= pitch * 0.4), None)
                    if cur is None:
                        taken = {id(q) for q in mine.pilots if q.y and any(abs(q.y - o.y) <= pitch * 0.4 for o in theirs.pilots if o is not p)}
                        cur = next((q for q in mine.pilots if id(q) not in taken and name_score(q.pilot, p.pilot) >= 0.86), None)
                    if cur is None:
                        p.votes = {p.pilot: 1}
                        mine.pilots.append(p); changed = True; continue
                    # the spelling seen most often wins, so one bad read cannot rename a pilot
                    cur.votes[p.pilot] = cur.votes.get(p.pilot, 0) + 1
                    best_name = max(cur.votes.items(), key=lambda kv: (kv[1], len(kv[0])))[0]
                    if best_name != cur.pilot:
                        cur.pilot = best_name; changed = True
                    for f in ("health", "alive", "kills", "assists"):
                        v = getattr(p, f)
                        if v is not None and getattr(cur, f) != v:
                            # a dead mech's health stays where the table left it
                            if f == "health" and not cur.alive and p.alive is False:
                                continue
                            setattr(cur, f, v); changed = True
                    if p.code and (cur.code != p.code or cur.variant != p.variant) and p.conf >= cur.conf:
                        cur.code, cur.variant, cur.name, cur.tons, cur.cls, cur.faction, cur.conf = p.code, p.variant, p.name, p.tons, p.cls, p.faction, p.conf
                        changed = True
                    cur.y = p.y
                mine.pilots.sort(key=lambda q: q.y)
            if fr.clock and fr.clock != self.clock: self.clock = fr.clock; changed = True
            if fr.caps and fr.caps != self.caps: self.caps = fr.caps; changed = True
            self.updated = fr.ts; self.frames += 1
            self._note_progress()
        if fr.highlight:
            h = fr.highlight
            p = self._find(h["pilot"]) if h.get("pilot") else None
            if p is None and h.get("code"):
                cands = [q for q in self.left.pilots + self.right.pilots if q.code == h["code"] and (not h.get("variant") or q.variant == h["variant"])]
                if len(cands) == 1:
                    p = cands[0]
            if p is not None:
                if h.get("loadout") and p.loadout != h["loadout"]:
                    p.loadout = h["loadout"]; changed = True
                if h.get("health") is not None and p.alive and p.health != h["health"]:
                    p.health = h["health"]; changed = True
                if h.get("code") and not p.code:
                    p.code, p.variant, p.name, p.tons, p.cls = h["code"], h.get("variant", ""), h.get("name", ""), h.get("tons", 0), h.get("cls", "")
                    changed = True
                hl = {"pilot": p.pilot, "side": "left" if p in self.left.pilots else "right"}
            else:
                hl = {"pilot": h.get("pilot", ""), "side": ""}
            if hl != self.highlight:
                self.highlight = hl; changed = True
            self.highlight_ts = fr.ts
        elif self.highlight and fr.kind == "comp" and fr.ts - self.highlight_ts > 6:
            self.highlight = None; changed = True
        return changed

    def as_dict(self) -> dict | None:
        if not self.left.pilots and not self.right.pilots:
            return None
        def team(t: CompTeam, side: str):
            ps = []
            for p in t.pilots:
                d = asdict(p); d["side"] = side; d.pop("votes", None)
                d["stats"] = weapondb.summary(p.loadout)
                ps.append(d)
            return {"name": t.name, "tag": t.tag, "series": t.series, "score": t.score, "pilots": ps,
                    "alive": sum(1 for p in t.pilots if p.alive), "tons": sum(p.tons for p in t.pilots),
                    "kills": sum(p.kills or 0 for p in t.pilots)}
        return {"left": team(self.left, "left"), "right": team(self.right, "right"), "clock": self.clock, "caps": self.caps,
                "progress": self._progress(),
                "highlight": self.highlight, "started": self.started, "updated": self.updated, "frames": self.frames}
