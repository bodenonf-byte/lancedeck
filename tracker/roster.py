"""The board's memory across frames.

A full roster is precious and is never thrown away by a weaker read:

  * a scoreboard read REPLACES the roster only on the first read of a match, or when it is
    clearly a new match (eight or more pilots of which few are already known);
  * any other scoreboard read (a partial one, a half-rendered table, the same match again)
    UPDATES the pilots it names — status, mech, lance, score — and adds pilots it did not
    know;
  * a lance-panel or Q-tag read updates health, deaths and mechs by pilot name;
  * a frame with nothing on it changes nothing, so the board holds while you look at the
    map or the mechlab.  RESET forgets everything.
"""
from __future__ import annotations

import difflib
import os
import re
import time

from .match import Slot, TeamState, set_known

from .paths import LOG


def _log(kind: str, s) -> None:
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 5_000_000:   # keep the log bounded: roll it once
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {kind:10s} {s.code or '?'}-{s.variant:<8s} {s.name:<16s} pilot={s.pilot!r:28s} hp={s.health} st={s.status} conf={s.conf:.2f} | {s.raw}\n")
    except Exception:
        pass


def _norm(a: str) -> str:
    return re.sub(r"\s+", "", a.lower().strip())


def _score(a: str, b: str) -> float:
    """How alike two pilot names are: 1 exact, 0.95 one contains the other (5+ chars), else
    the sequence ratio — but names whose DIGITS differ are different pilots (pilot3/pilot0,
    Tw1st3d vs Tw1st4d), whatever the letters say."""
    a = a.lower().strip(); b = b.lower().strip()
    if not a or not b or a in ("?", "spotted") or b in ("?", "spotted"):
        return 0.0
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return 1.0
    if re.sub(r"\D", "", na) != re.sub(r"\D", "", nb):
        return 0.0
    if len(na) >= 5 and len(nb) >= 5 and (na in nb or nb in na):
        return 0.95
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _same(a: str, b: str) -> bool:
    return _score(a, b) >= 0.86


TEAM_SIZE = 12


def _vkey(v: str) -> str:
    """A variant as OCR keeps confusing it: O/0, I/1, S/5, B/8 folded, dashes and spaces out."""
    return re.sub(r"[-\s]", "", (v or "").upper()).translate(str.maketrans("OIB", "018")).replace("S", "5")


def same_mech(a: Slot, b: Slot) -> bool:
    if not a.code or a.code != b.code:
        return False
    ka, kb = _vkey(a.variant), _vkey(b.variant)
    if ka == kb:
        return True
    # a digit glued on by OCR ("F" vs "F7", "PRIME" vs "PRIME9"): one is the other plus digits
    short, long_ = (ka, kb) if len(ka) < len(kb) else (kb, ka)
    return bool(short) and long_.startswith(short) and long_[len(short):].isdigit()


def _find(pool: list[Slot], s: Slot) -> Slot | None:
    best = None; best_score = 0.0
    for r in pool:
        sc = _score(r.pilot, s.pilot)
        if sc > best_score:
            best, best_score = r, sc
    hit = best if best_score >= 0.86 else None
    if hit is None and s.code:
        same_code = [r for r in pool if same_mech(r, s)]
        # a mech nobody else on this side drives: the same pilot, however OCR spelt him —
        # always when the side is already full, otherwise only for a nameless read
        if len(same_code) == 1 and (len(pool) >= TEAM_SIZE or s.pilot in ("?", "spotted") or same_code[0].pilot in ("?", "spotted")):
            hit = same_code[0]
        elif len(same_code) == 1 and best_score >= 0.6:
            hit = same_code[0]
    return hit


def _room(pool: list[Slot], s: Slot, side: str) -> bool:
    """May this side take one more pilot?  Twelve is the team.  A named pilot may evict a
    nameless "spotted" entry (the least confident) to get in; past that a read is noise."""
    if len(pool) < TEAM_SIZE:
        return True
    if s.pilot not in ("?", "spotted"):
        nameless = [r for r in pool if r.pilot in ("?", "spotted")]
        if nameless:
            victim = min(nameless, key=lambda r: r.conf)
            pool.remove(victim); _log("EVICTED-" + side, victim)
            return True
    _log("DROPPED-" + side, s)
    return False


def _set_alive(tgt: Slot, s: Slot, from_table: bool) -> None:
    """Deaths and revivals are debounced, because one misread panel row must not flip a seat.
    A table (TAB, results) is trusted at once for a death and revives on two ALIVE reads in a
    row.  A HUD read kills only when it says DEAD twice in a row, and revives only after three
    reads in a row that show the pilot alive WITH a health percentage."""
    if from_table:
        if not s.alive:
            if tgt.alive:
                _log("KILLED-TAB", s)
            tgt.alive = False; tgt.status = s.status or "DEAD"; tgt.health = None; tgt._revive = 0; tgt._dying = 0
            return
        if tgt.alive:
            if s.status and s.status != "?":
                tgt.status = s.status
            return
        tgt._revive = getattr(tgt, "_revive", 0) + 1
        if tgt._revive >= 2:
            _log("REVIVED-TAB", s)
            tgt.alive = True; tgt.status = s.status or "ALIVE"; tgt._revive = 0
        return
    # a HUD read
    if not s.alive:
        tgt._revive = 0
        if not tgt.alive:
            return
        tgt._dying = getattr(tgt, "_dying", 0) + 1
        if tgt._dying >= 2:
            _log("KILLED-HUD", s)
            tgt.alive = False; tgt.status = "DEAD"; tgt.health = None; tgt._dying = 0
        return
    tgt._dying = 0
    if tgt.alive:
        if s.status and s.status not in ("?", "SEEN"):
            tgt.status = s.status
        return
    if s.health is not None:
        tgt._revive = getattr(tgt, "_revive", 0) + 1
        if tgt._revive >= 3:
            _log("REVIVED-HUD", s)
            tgt.alive = True; tgt.status = "ALIVE"; tgt._revive = 0


def _take_mech(tgt: Slot, s: Slot) -> None:
    tgt.code, tgt.variant, tgt.name, tgt.tons, tgt.cls = s.code, s.variant, s.name, s.tons, s.cls
    tgt.faction, tgt.pros, tgt.cons = s.faction, s.pros, s.cons
    tgt.guess = False                                    # read this match: no longer a supposition


def _memkey(pilot: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (pilot or "").lower())


class Roster:
    def __init__(self):
        self.mine: list[Slot] = []
        self.enemy: list[Slot] = []
        self.updated = 0.0
        self.last_kind = "none"
        self.hud_hits = 0
        self.map = ""
        self.result = ""
        self.mode = ""
        self.frozen = False            # the initial matchup is in; no pilot is added after this
        self.seen: list[Slot] = []     # enemy mechs sighted without a pilot to hang them on
        self._foreign = 0              # full table reads in a row that name a different set of pilots
        self.match_id = ""             # names the match's record file; new matchup = new id
        self.started = 0.0
        self.memory: dict[str, dict] = {}   # pilot -> the mech he drove in a recent game (last 5 records)
        self.last_target: tuple | None = None   # (pilot, code, variant, ts) from the reticle's target readout

    # ── scoreboard ───────────────────────────────────────────────────────────
    def _scoreboard(self, st: TeamState) -> None:
        new_names = {s.pilot.lower() for s in st.mine + st.enemy if s.pilot not in ("?", "")}
        old_names = {s.pilot.lower() for s in self.mine + self.enemy if s.pilot not in ("?", "")}
        overlap = len(new_names & old_names) / max(1, len(new_names))
        drop = st.note == "drop preparation"
        full = len(st.mine) >= (6 if drop else 8)
        # a full table is the matchup: while nothing is frozen yet (a roster pieced together from
        # the HUD after a restart is noisy: name variants, mis-paired mechs) it REPLACES the board
        first = not self.mine or (not self.frozen and full)
        new_match = bool(full and old_names and overlap < 0.4)
        # the next match's loading screen after a finished one is a new match even when the
        # same pilots queued again — their mechs may have changed
        if drop and full and self.result:
            new_match = True; self._foreign = 0
        elif new_match and self.frozen:
            # a frozen matchup is not thrown away by one odd read: only the next match's
            # loading screen, or two full tables in a row that do not know these pilots
            self._foreign += 1
            new_match = drop or self._foreign >= 2
        elif full and overlap >= 0.4:
            self._foreign = 0
        if first or new_match:
            self._foreign = 0
            self.match_id = time.strftime("%Y-%m-%d_%H%M%S"); self.started = time.time()
            if st.map: self.map = st.map
            if getattr(st, "mode", ""): self.mode = st.mode
            self.mine = st.mine[:TEAM_SIZE]; self.enemy = st.enemy[:TEAM_SIZE]
            self.result = st.result or ""
            self.seen = []
            for s in self.mine + self.enemy:
                if s.code: s.locked = True
            self.frozen = len(self.mine) >= 8 and len(self.enemy) >= 8
            if st.mine:
                _log("FROZEN" if self.frozen else "ROSTER", st.mine[0])
            return
        # otherwise: update what it names, add what is new, never remove
        for side_new, side_old in ((st.mine, self.mine), (st.enemy, self.enemy)):
            for s in side_new:
                tgt = _find(side_old, s)
                if tgt is None and not self.frozen:
                    # a pilot named on the other side of an earlier read (a mis-split) moves over —
                    # never once the matchup is frozen: seats do not move
                    other = self.enemy if side_old is self.mine else self.mine
                    o = _find(other, s)
                    if o is not None:
                        other.remove(o); side_old.append(o); tgt = o
                if tgt is None:
                    # frozen: a table may still fill an empty seat with a NAMED pilot, never past twelve
                    if self.frozen and (len(side_old) >= TEAM_SIZE or s.pilot in ("?", "spotted")):
                        _log("FROZEN-SKIP", s); continue
                    if not _room(side_old, s, "MINE" if side_old is self.mine else "ENEMY"):
                        continue
                    _log("NEW-" + ("MINE" if side_old is self.mine else "ENEMY"), s)
                    side_old.append(s); continue
                _set_alive(tgt, s, True)
                if s.code and (tgt.code is None or tgt.guess or (not tgt.locked and s.conf >= tgt.conf)):
                    _take_mech(tgt, s); tgt.conf = s.conf; tgt.locked = True
                if s.lance:
                    tgt.lance = s.lance
                if s.score is not None:
                    tgt.score = s.score
                if s.pilot not in ("?", "") and tgt.pilot in ("?", "spotted"):
                    tgt.pilot = s.pilot
        # the matchup is in once both sides are (nearly) complete: from here on nobody is added
        # from the HUD, and a mech tied to a pilot stays
        if not self.frozen and len(self.mine) >= 8 and len(self.enemy) >= 8:
            self.frozen = True; _log("FROZEN", self.mine[0])
        if st.result:
            self.result = st.result
        if any(s.medal for s in st.mine + st.enemy):
            for s in self.mine + self.enemy:
                s.medal = 0
            for s in st.mine + st.enemy:
                if s.medal:
                    t = _find(self.mine if s in st.mine else self.enemy, s)
                    if t is not None:
                        t.medal = s.medal; t.score = s.score

    # ── hud: lance panel + Q tags + sightings ────────────────────────────────
    def _hud(self, st: TeamState) -> None:
        for s in st.mine:
            tgt = _find(self.mine, s)
            if tgt is None and s.pilot not in ("?", "spotted") and not self.frozen:
                o = _find(self.enemy, s)
                if o is not None:                                # named blue: he is mine, whatever an earlier split said
                    self.enemy.remove(o); self.mine.append(o); tgt = o
            if tgt is None:
                if self.frozen or not _room(self.mine, s, "MINE"):
                    _log("FROZEN-SKIP", s); continue
                _log("NEW-MINE", s); self.mine.append(s); continue
            _set_alive(tgt, s, False)
            if tgt.alive and s.health is not None:
                tgt.health = min(100, s.health)
            if s.lance:
                tgt.lance = s.lance
            if s.code and (tgt.code is None or tgt.guess):
                _take_mech(tgt, s)
                self.seen = [x for x in self.seen if not same_mech(x, s)]      # it was one of ours all along
            if s.pilot not in ("?", "spotted") and tgt.pilot in ("?", "spotted"):
                tgt.pilot = s.pilot
        for s in st.enemy:
            if s.pilot not in ("spotted", "?") and s.code:
                self.last_target = (s.pilot, s.code, s.variant, time.time())
            if s.pilot not in ("spotted", "?"):
                mine_hit = _find(self.mine, s)
                if mine_hit is not None:                         # a targeted teammate: update, never list as enemy
                    if s.health is not None:
                        mine_hit.health = min(100, s.health)
                    continue
            tgt = _find(self.enemy, s)
            if tgt is None and s.pilot in ("spotted", "?") and any(same_mech(r, s) for r in self.mine)                     and not any(same_mech(r, s) for r in self.enemy):
                _log("MINE-SEEN", s); continue                    # a teammate's mech read off the HUD, not an enemy
            if tgt is None:
                if s.pilot in ("spotted", "?") or self.frozen:
                    # no pilot to hang it on: the seen pool (one entry per mech), never a new player
                    hit = next((x for x in self.seen if same_mech(x, s)), None)
                    if hit is None:
                        if len(self.seen) < 12:
                            self.seen.append(s); _log("SEEN-POOL", s)
                    else:
                        if s.health is not None: hit.health = min(100, s.health)
                        if s.status == "DEAD": hit.alive = False; hit.status = "DEAD"
                    continue
                if not _room(self.enemy, s, "ENEMY"):
                    continue
                _log("NEW-ENEMY", s); self.enemy.append(s); continue
            if s.code and (tgt.code is None or tgt.guess or (tgt.status == "SEEN" and not tgt.locked)):
                _take_mech(tgt, s)
                if s.pilot not in ("spotted", "?"):
                    tgt.locked = True
                    self.seen = [x for x in self.seen if not same_mech(x, s)]      # it has a pilot now
            _set_alive(tgt, s, False)
            if tgt.alive:
                if s.health is not None:
                    tgt.health = min(100, s.health)
                if tgt.status in ("?", "SEEN") and s.status not in ("?", ""):
                    tgt.status = s.status
            if tgt.pilot in ("spotted", "?") and s.pilot not in ("spotted", "?"):
                tgt.pilot = s.pilot

    def _target(self, st: TeamState) -> None:
        """The target info panel names the locked mech's variant and weapons.  The seat is the
        pilot the reticle readout named a moment ago when the mechs agree, else the one seat on
        either side that drives this very mech.  A loadout, once read, stays."""
        s = st.enemy[0]
        seat = None
        lt = self.last_target
        if lt and time.time() - lt[3] < 8 and lt[1] == s.code:
            for pool in (self.enemy, self.mine):
                seat = next((r for r in pool if _same(r.pilot, lt[0])), None)
                if seat: break
        if seat is None:
            cands = [r for r in self.enemy + self.mine if same_mech(r, s) and not r.guess]
            if len(cands) == 1:
                seat = cands[0]
        if seat is None:
            return
        if seat.loadout != s.loadout:
            seat.loadout = s.loadout; _log("LOADOUT", s)
        if seat.code is None or seat.guess:
            _take_mech(seat, s)

    def merge(self, st: TeamState) -> TeamState:
        if st.kind == "target" and st.enemy:
            self._target(st); self.updated = st.ts
            out = TeamState(self.last_kind, list(self.mine), list(self.enemy), st.source, self.updated or st.ts, st.frame_w, st.frame_h, "", self.map)
            out.result = self.result; out.mode = self.mode; out.seen = list(self.seen); out.frozen = self.frozen
            return out
        # the lance setup stays up after the match — through the results, the MechLab, the queue —
        # until the next match's loading screen replaces it.  A map name read on some other
        # screen (an event banner, the map list) is not a new match and changes nothing.
        if st.map and st.kind != "none":
            if st.note == "drop preparation" or not self.map:
                self.map = st.map
        if getattr(st, "mode", "") and (st.note == "drop preparation" or not self.mode):
            self.mode = st.mode
        if st.kind == "scoreboard" and st.mine:
            self._scoreboard(st); self.updated = st.ts; self.last_kind = "scoreboard"
        elif st.kind == "hud" and (st.mine or st.enemy):
            self._hud(st); self.updated = st.ts; self.last_kind = "hud"; self.hud_hits += 1
        self._suppose()
        set_known([s.pilot for s in self.mine + self.enemy])
        out = TeamState(self.last_kind, list(self.mine), list(self.enemy), st.source,
                        self.updated or st.ts, st.frame_w, st.frame_h, st.note, self.map)
        out.result = self.result; out.mode = self.mode
        out.seen = list(self.seen); out.frozen = self.frozen
        return out

    def _suppose(self) -> None:
        """A pilot seen in one of the last games, whose mech this match has not shown yet, is
        given that mech as a guess — drawn as such, replaced by the first real read."""
        if not self.memory:
            return
        for s in self.mine + self.enemy:
            if s.code or s.pilot in ("?", "spotted", ""):
                continue
            m = self.memory.get(_memkey(s.pilot))
            if not m or not m.get("code"):
                continue
            s.code, s.variant, s.name, s.tons, s.cls = m["code"], m.get("variant", ""), m.get("name", ""), m.get("tons", 0), m.get("cls", "Unknown")
            s.faction, s.pros, s.cons = m.get("faction", ""), m.get("pros", ""), m.get("cons", "")
            s.guess = True; s.locked = False; s.conf = 0.0
            _log("SUPPOSED", s)

    def clear(self):
        self.mine = []; self.enemy = []; self.updated = time.time(); self.last_kind = "none"; self.map = ""; self.result = ""; self.mode = ""; self.frozen = False; self.seen = []; self.match_id = ""
