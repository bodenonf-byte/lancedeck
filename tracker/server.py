"""The local service: two capture loops + OCR + matcher + roster, FastAPI in front.

  panel loop   `fps` times a second: the lance-panel corner only (~60 ms on the GPU) —
               your lance's health and deaths, near-live
  full loop    every `full_every` seconds: the whole frame — the TAB scoreboard, Q tags,
               the target readout, the map name

GET  /                  the team board
GET  /calib             the calibration view (last full frame with OCR boxes and the panel region)
GET  /api/state         the roster as JSON
GET  /api/frame.jpg     the last full frame (with boxes when ?boxes=1)
POST /api/screenshot    multipart image -> analysed like a full frame (a dev aid; play needs none)
POST /api/live          {"on": true|false} toggles both loops
POST /api/reset         forget the current match
WS   /ws                pushes the state whenever it changes
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import shutil
import re
import os
import threading
import time

from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

from .capture import Grabber
from .match import build, TeamState
from .mechdb import MechDB
from .ocr import Reader, Line
from .roster import Roster

from . import paths
from .paths import ROOT, WEB, RECORDS, ASSETS, CFG_PATH, CFG_DEFAULT, APP, VERSION
HERE = os.path.dirname(os.path.abspath(__file__))
paths.ensure_dirs()
if not os.path.exists(CFG_PATH):
    shutil.copyfile(CFG_DEFAULT, CFG_PATH)


class Service:
    def __init__(self):
        with open(CFG_PATH, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.db = MechDB()
        dml = bool(self.cfg.get("ocr_dml", False))
        try:                                            # stay out of the game's way: below-normal priority
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
        except Exception:
            pass
        # ONE session for both loops: two DirectML sessions running at once take the GPU
        # device down ("device instance has been suspended"); serialised, a panel read is
        # ~60 ms and a full 3440x1440 read ~250 ms, so the panel loop barely notices
        self.reader = Reader(use_dml=dml, threads=int(self.cfg.get('ocr_threads', 4)))
        self.ocr_lock = threading.Lock()
        # on the CPU the corners get a reader of their own, so a slow full-frame read never
        # holds up a death or a health bar; on the GPU one engine is shared (two DirectML
        # sessions crash the device)
        if self.reader.backend == "dml":
            self.reader_panel, self.panel_lock = self.reader, self.ocr_lock
        else:
            self.reader_panel = Reader(use_dml=False, threads=max(1, int(self.cfg.get("ocr_threads_panel", 2))))
            self.panel_lock = threading.Lock()
        self.grabber = Grabber(int(self.cfg.get("monitor", 1)))
        self.state: TeamState | None = None
        self.last_frame: Image.Image | None = None
        self.last_lines: list[Line] = []
        self.version = 0
        self.live = bool(self.cfg.get("live", True))
        self.lock = threading.Lock()
        self.stats = {"frames": 0, "panel_frames": 0, "ocr_ms": 0, "panel_ms": 0, "last_error": "",
                      "last_kind": "none", "ocr": self.reader.backend, "capture": self.grabber.backend,
                      "screen": list(self.grabber.size()), "target": self.grabber.describe()}
        self.roster = Roster()
        self.roster.memory = load_memory()
        self.grabber.window_mode = self.cfg.get("capture", "window") != "screen"
        self.assets_v = 0              # bumps when a picture is harvested, so the page refetches the list
        self._map_since = 0.0; self._map_seen = ""
        from .match import set_panel_region
        set_panel_region(self.cfg.get("panel_region") or [0.0, 0.0, 0.36, 0.26])
        threading.Thread(target=self._full_loop, daemon=True).start()
        threading.Thread(target=self._panel_loop, daemon=True).start()

    def _apply(self, raw: TeamState, img: Image.Image, lines: list[Line], full: bool, ms: int):
        with self.lock:
            st = self.roster.merge(raw)
            if full:
                self.last_frame = img; self.last_lines = lines
                self.stats["frames"] += 1; self.stats["ocr_ms"] = ms; self.stats["last_kind"] = raw.kind
            else:
                self.stats["panel_frames"] += 1; self.stats["panel_ms"] = ms
            if raw.kind != "none" or raw.map or self.state is None or getattr(st, "spectating", "") != getattr(self.state, "spectating", ""):
                self.state = st; self.version += 1
        # a record needs the real results screen: a VICTORY/DEFEAT read, or a scored table with
        # most pilots carrying a match score — never a mid-match TAB
        scored = sum(1 for s_ in st.mine + st.enemy if s_.score is not None)
        if full and raw.kind == "scoreboard" and (raw.result or (raw.note == "end table" and scored >= 12)) and (st.mine or st.enemy):
            self._record(img, st)
        return st

    def _record(self, img: Image.Image, st: TeamState):
        """The final screen of the match — results, scores, medals — kept under records/ with the
        roster as read.  Re-read while the screen is up, it overwrites the same match's record."""
        try:
            mid = self.roster.match_id or time.strftime("%Y-%m-%d_%H%M%S")
            if not self.roster.match_id:
                self.roster.match_id = mid
            os.makedirs(RECORDS, exist_ok=True)
            im = img if img.width <= 1720 else img.resize((1720, int(img.height * 1720 / img.width)), Image.LANCZOS)
            im.convert("RGB").save(os.path.join(RECORDS, mid + ".jpg"), quality=82, optimize=True)
            d = st.as_dict(); d["match_id"] = mid; d["saved"] = time.time()
            d["started"] = self.roster.started or time.time()
            with open(os.path.join(RECORDS, mid + ".json"), "w", encoding="utf-8") as f:
                json.dump(d, f)
            if self.stats.get("last_record") != mid:
                self.stats["last_record"] = mid; self.version += 1
            self.roster.memory = load_memory()
            self.records_v = getattr(self, "records_v", 0) + 1
        except Exception as e:
            self.stats["last_error"] = "record: " + repr(e)[:160]

    def analyse(self, img: Image.Image, source: str):
        """A full-frame read (the full loop, or a dropped screenshot)."""
        t0 = time.time()
        with self.ocr_lock:
            lines = self.reader.read(img, float(self.cfg.get("ocr_scale", 1.0)))
        raw = build(lines, img, self.db, self.cfg, source)
        if source == "live":
            self._sample(img, lines, raw)
            self._harvest(img, lines, raw)
        return self._apply(raw, img, lines, True, round((time.time() - t0) * 1000))

    def _harvest(self, img, lines, raw):
        """Pictures from the player's own screen: mech portraits off the MechLab home screen,
        one gameplay frame per map as its backdrop."""
        try:
            from . import harvest
            got = harvest.harvest_mech(img, lines, self.db) or harvest.harvest_grid(img, lines, self.db)
            if got:
                self.assets_v += 1; self.stats["last_harvest"] = ", ".join(got); self.version += 1
            m = self.roster.map
            if m != self._map_seen:
                self._map_seen = m; self._map_since = time.time()
            # the loading screen shows the map itself: take it the moment the map is known;
            # a gameplay frame 45 s in is the fallback when the loading screen was missed
            want = (raw.note == "drop preparation" and raw.map) or (raw.kind == "hud" and time.time() - self._map_since > 45)
            if m and want and self.cfg.get("harvest_maps", False) and not harvest.have_map(m):   # off: the game's own art is used
                f = harvest.harvest_map(img, m)
                if f:
                    self.assets_v += 1; self.stats["last_harvest"] = f; self.version += 1
        except Exception as e:
            self.stats["last_error"] = "harvest: " + repr(e)[:160]

    # frames worth keeping for tuning: the end-of-match table, a TAB scoreboard, a Q overlay
    # with tags, a MechLab screen with a variant on it — a few of each, in samples/
    SAMPLE_KINDS = {"end": 4, "scoreboard": 3, "drop": 3, "qtags": 4, "mechlab": 6, "grid": 4, "oversize": 4}

    def _sample(self, img, lines, raw):
        sdir = paths.SAMPLES; os.makedirs(sdir, exist_ok=True)
        text = " ".join(l.text for l in lines).upper()
        kind = None
        if raw.kind == "scoreboard" and (len(raw.mine) + len(raw.enemy) > 24 or "oversize" in raw.note):
            kind = "oversize"
        elif raw.kind == "scoreboard" and (raw.result or raw.note == "end table"):
            kind = "end"
        elif raw.kind == "scoreboard" and raw.note == "drop preparation":
            kind = "drop"                                        # the loading screen: what a matchup was read from
        elif raw.kind == "scoreboard":
            kind = "scoreboard"
        elif raw.kind == "hud" and (raw.enemy or len(raw.mine) > 4):
            kind = "qtags"
        elif ("MECHLAB" in text or "LOADOUT" in text or "MECH LAB" in text) and any(True for l in lines for _ in __import__("tracker.mechdb", fromlist=["find_tokens"]).find_tokens(l.text)):
            from . import harvest
            kind = "grid" if harvest.is_frontend(lines) and len(harvest.grid_labels(lines, self.db)) >= 3 else "mechlab"
        if kind is None:
            return
        last = self.stats.get("last_sample_" + kind, 0)
        if time.time() - last < 20:
            return
        self.stats["last_sample_" + kind] = time.time()
        have = sorted(f for f in os.listdir(sdir) if f.startswith(kind + "_") and "_small" not in f)
        while len(have) >= self.SAMPLE_KINDS[kind]:              # rolling: the oldest makes room
            try: os.remove(os.path.join(sdir, have.pop(0)))
            except OSError: break
        img.save(os.path.join(sdir, f"{kind}_{time.strftime('%H%M%S')}.jpg"), quality=85)

    def analyse_target(self, img: Image.Image):
        """The top-right target info panel: the locked mech's variant and weapons."""
        from .match import target_panel
        t0 = time.time()
        with self.panel_lock:
            lines = self.reader_panel.read(img, 1.0)
        raw = target_panel(lines, img, self.db)
        if raw.kind == "target":
            with self.lock:
                st = self.roster.merge(raw); self.state = st; self.version += 1
                self.stats["target_ms"] = round((time.time() - t0) * 1000)
        return raw

    def analyse_panel(self, img: Image.Image):
        t0 = time.time()
        with self.panel_lock:
            lines = self.reader_panel.read(img, 1.0)
        raw = build(lines, img, self.db, self.cfg, "panel")
        if raw.kind != "hud":                              # the corner holds nothing but the panel; anything else is noise
            raw = TeamState("none", [], [], "panel", time.time(), img.width, img.height, "")
        return self._apply(raw, img, lines, False, round((time.time() - t0) * 1000))

    def reset(self):
        with self.lock:
            self.roster.clear(); self.version += 1
            self.state = TeamState("none", [], [], "reset", time.time(), 0, 0, "roster cleared")

    def _full_loop(self):
        while True:
            if not self.live:
                time.sleep(0.25); continue
            t0 = time.time()
            try:
                img = self.grabber.grab()
                if img is not None:
                    self.analyse(img, "live")
            except Exception as e:
                self.stats["last_error"] = "full: " + repr(e)[:160]
            every = max(0.3, float(self.cfg.get("full_every", 1.0)))
            time.sleep(max(0.0, every - (time.time() - t0)))

    def _panel_loop(self):
        while True:
            if not self.live:
                time.sleep(0.25); continue
            t0 = time.time()
            try:
                # one grab of the window per tick, both corners cropped out of it
                region = self.cfg.get("panel_region") or [0.0, 0.0, 0.36, 0.26]
                treg = self.cfg.get("target_region") or [0.64, 0.0, 0.94, 0.28]
                self._tick = getattr(self, "_tick", 0) + 1
                frame = self.grabber.grab()
                if frame is not None:
                    W, H = frame.size
                    crop = lambda r: frame.crop((int(r[0] * W), int(r[1] * H), int(r[2] * W), int(r[3] * H)))
                    self.analyse_panel(crop(region))
                    if self._tick % 2 == 0:                 # every other tick: the target info panel, top right
                        self.analyse_target(crop(treg))
            except Exception as e:
                self.stats["last_error"] = "panel: " + repr(e)[:160]
            dt = 1.0 / max(0.5, float(self.cfg.get("fps", 6)))
            time.sleep(max(0.0, dt - (time.time() - t0)))

    def frame_png(self, boxes: bool) -> bytes | None:
        with self.lock:
            img = self.last_frame; lines = list(self.last_lines)
        if img is None:
            return None
        im = img.copy()
        if boxes:
            d = ImageDraw.Draw(im)
            for ln in lines:
                d.rectangle([ln.x0, ln.y0, ln.x1, ln.y1], outline=(250, 189, 61), width=2)
                d.text((ln.x0, max(0, ln.y0 - 12)), ln.text[:40], fill=(250, 189, 61))
            r = self.cfg.get("panel_region") or [0, 0, 0.36, 0.26]
            d.rectangle([r[0] * im.width, r[1] * im.height, r[2] * im.width, r[3] * im.height], outline=(77, 216, 216), width=3)
            t = self.cfg.get("target_region") or [0.64, 0.0, 0.94, 0.28]
            d.rectangle([t[0] * im.width, t[1] * im.height, t[2] * im.width, t[3] * im.height], outline=(255, 140, 60), width=3)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=80)
        return buf.getvalue()

    def payload(self):
        self.stats["target"] = self.grabber.describe(); self.stats["screen"] = list(self.grabber.size())
        if self.state is None:
            return {"kind": "none", "mine": [], "enemy": [], "source": "none", "ts": 0, "note": "no frame yet", "map": "",
                    "version": self.version, "stats": self.stats, "live": self.live, "my_name": self.cfg.get("my_name", "")}
        d = self.state.as_dict(); d["version"] = self.version; d["stats"] = self.stats; d["live"] = self.live
        d["result"] = getattr(self.state, "result", ""); d["mode"] = getattr(self.state, "mode", "")
        d["frozen"] = getattr(self.state, "frozen", False)
        d["my_name"] = self.cfg.get("my_name", ""); d["assets_v"] = self.assets_v
        d["donate_url"] = self.cfg.get("donate_url", ""); d["app"] = APP; d["app_version"] = VERSION
        d["records_v"] = getattr(self, "records_v", 0)
        return d


MEMORY_GAMES = 5


def load_memory() -> dict:
    """pilot -> mech from the last MEMORY_GAMES records: who drove what, both teams."""
    mem: dict[str, dict] = {}
    if not os.path.isdir(RECORDS):
        return mem
    files = sorted((f for f in os.listdir(RECORDS) if f.endswith(".json")), reverse=True)[:MEMORY_GAMES]
    for f in reversed(files):                           # oldest first, so the latest game wins
        try:
            with open(os.path.join(RECORDS, f), encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        for s in d.get("mine", []) + d.get("enemy", []):
            if s.get("code") and not s.get("guess") and s.get("pilot") not in ("?", "spotted", ""):
                key = re.sub(r"[^a-z0-9]", "", s["pilot"].lower())
                mem[key] = {k: s.get(k) for k in ("code", "variant", "name", "tons", "cls", "faction", "pros", "cons")}
                mem[key]["game"] = d.get("match_id", f[:-5])
    return mem


svc: Service | None = None
app = FastAPI(title="MechWarrior Online Team Tracker")


@app.on_event("startup")
def _start():
    global svc
    svc = Service()


def _configured() -> bool:
    """Set up = the pictures have been imported once.  The pilot name is wanted but not
    required: the page has its own PILOT box and works without it."""
    mechs = os.path.join(ASSETS, "mechs")
    return os.path.isdir(mechs) and any(f.endswith(".png") for f in os.listdir(mechs))


@app.get("/")
def index():
    if not _configured():
        return RedirectResponse("/setup")
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/setup")
def setup_page():
    return FileResponse(os.path.join(WEB, "setup.html"))


_setup = {"running": False, "log": [], "done": False, "error": ""}


@app.get("/api/setup/status")
def setup_status():
    from tools.import_game_icons import find_game
    mechs = os.path.join(ASSETS, "mechs"); maps = os.path.join(ASSETS, "maps"); cut = os.path.join(mechs, "cut")
    count = lambda d, ext: len([f for f in os.listdir(d) if f.lower().endswith(ext)]) if os.path.isdir(d) else 0
    return {"app": APP, "version": VERSION, "game": find_game(svc.cfg.get("game_dir") if svc else None),
            "my_name": svc.cfg.get("my_name", "") if svc else "", "donate_url": svc.cfg.get("donate_url", "") if svc else "",
            "icons": count(mechs, ".png"), "maps": count(maps, ".jpg"), "cut": count(cut, ".png"),
            "running": _setup["running"], "log": _setup["log"][-40:], "done": _setup["done"], "error": _setup["error"],
            "configured": _configured()}


@app.post("/api/setup/import")
async def setup_import(body: dict):
    """Import the icons and map art from the game install, then cut the mechs out — in the
    background, progress in /api/setup/status."""
    if _setup["running"]:
        return {"ok": False, "why": "already running"}
    game = body.get("game_dir") or (svc.cfg.get("game_dir") if svc else None)
    if game and svc:
        svc.cfg["game_dir"] = game
    if body.get("my_name") is not None and svc:
        svc.cfg["my_name"] = body["my_name"].strip()
    if svc:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(svc.cfg, f, indent=2)

    def run():
        import contextlib, io
        _setup.update(running=True, log=[], done=False, error="")

        class Tee(io.StringIO):
            def write(self, t):
                for line in t.splitlines():
                    if line.strip():
                        _setup["log"].append(line.strip())
                return len(t)
        try:
            from tools import import_game_icons, import_game_maps, cut_mech_icons
            with contextlib.redirect_stdout(Tee()):
                for name, mod in (("icons", import_game_icons), ("maps", import_game_maps), ("cut-outs", cut_mech_icons)):
                    _setup["log"].append(f"== {name}")
                    old = sys.argv; sys.argv = [old[0]] + ([game] if game and mod is not cut_mech_icons else [])
                    try:
                        mod.main()
                    finally:
                        sys.argv = old
            if svc:
                svc.assets_v += 1; svc.version += 1
            _setup["done"] = True
        except Exception as e:
            _setup["error"] = repr(e)[:300]
        finally:
            _setup["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


@app.get("/calib")
def calib():
    return FileResponse(os.path.join(WEB, "calib.html"))


@app.get("/api/state")
def state():
    return JSONResponse(svc.payload() if svc else {"kind": "none", "mine": [], "enemy": [], "version": 0, "note": "starting"})


@app.get("/api/frame.jpg")
def frame(boxes: int = 0):
    data = svc.frame_png(bool(boxes)) if svc else None
    if data is None:
        return Response(status_code=404)
    return Response(content=data, media_type="image/jpeg")


@app.post("/api/screenshot")
async def screenshot(file: UploadFile):
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    was = svc.live; svc.live = False          # a dropped image holds until live is switched back on
    svc.analyse(img, "screenshot:" + (file.filename or "upload"))
    d = svc.payload(); d["was_live"] = was
    return JSONResponse(d)


@app.post("/api/live")
async def live(body: dict):
    svc.live = bool(body.get("on", True))
    return {"live": svc.live}


@app.post("/api/reset")
async def reset():
    svc.reset()
    return {"ok": True}


quit_hook = None      # set by the tray launcher: stops the tray icon and the server politely


@app.post("/api/quit")
async def quit_app():
    """Stop LanceDeck from the page: the tray icon and the server go through the launcher's
    hook when there is one; a second later the process ends whatever happened, so a helper
    started from a console (python -m tracker) stops too."""
    def _bye():
        time.sleep(0.4)
        try:
            if quit_hook:
                quit_hook()
        except Exception:
            pass
        time.sleep(1.2)
        os._exit(0)
    threading.Thread(target=_bye, daemon=True).start()
    return {"ok": True, "bye": True}


@app.get("/api/records")
def records():
    """Every match's final screen, newest first: the roster as read plus the screenshot's name."""
    out = []
    if os.path.isdir(RECORDS):
        for f in sorted(os.listdir(RECORDS), reverse=True):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(RECORDS, f), encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            mid = f[:-5]
            top = sorted([s for s in d.get("mine", []) if s.get("medal")], key=lambda s: s["medal"]) + sorted([s for s in d.get("enemy", []) if s.get("medal")], key=lambda s: s["medal"])
            out.append({"match_id": mid, "image": f"/records/{mid}.jpg" if os.path.exists(os.path.join(RECORDS, mid + ".jpg")) else None,
                        "map": d.get("map", ""), "mode": d.get("mode", ""), "result": d.get("result", ""), "saved": d.get("saved"), "started": d.get("started"),
                        "mine": len(d.get("mine", [])), "enemy": len(d.get("enemy", [])),
                        "mine_alive": sum(1 for s in d.get("mine", []) if s.get("alive")), "enemy_alive": sum(1 for s in d.get("enemy", []) if s.get("alive")),
                        "medals": [{"medal": s["medal"], "pilot": s["pilot"], "name": s.get("name"), "code": s.get("code"), "variant": s.get("variant"), "score": s.get("score"),
                                    "side": "mine" if s in d.get("mine", []) else "enemy"} for s in top[:6]],
                        "me": next((s for s in d.get("mine", []) if svc and svc.cfg.get("my_name") and svc.cfg["my_name"].lower().replace(" ", "") in (s.get("pilot") or "").lower().replace(" ", "")), None)})
    return out


@app.get("/api/mymechs")
def my_mechs():
    """What the pilot has played, mech by mech, out of the records: games, wins, scores, medals,
    survival — the MECH BOARD."""
    me = (svc.cfg.get("my_name") if svc else "") or ""
    key = re.sub(r"[^a-z0-9]", "", me.lower())
    # A per-mech stats reset does not touch the records: it only moves the point that mech's
    # column counts from.  stats_since = {"RVN-4X": epoch, ...}
    since_map = _since_map()
    mechs: dict[str, dict] = {}
    total = {"games": 0, "wins": 0, "losses": 0, "score": 0, "best": 0, "medals": [0, 0, 0], "survived": 0}
    if not key or not os.path.isdir(RECORDS):
        return {"pilot": me, "total": total, "mechs": []}
    for f in sorted(os.listdir(RECORDS)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(RECORDS, f), encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        mine = d.get("mine", [])
        s = next((x for x in mine if key and (key in re.sub(r"[^a-z0-9]", "", (x.get("pilot") or "").lower()) or re.sub(r"[^a-z0-9]", "", (x.get("pilot") or "").lower()) in key) and len(re.sub(r"[^a-z0-9]", "", (x.get("pilot") or "").lower())) >= 3), None)
        if not s or not s.get("code"):
            continue
        mid = f"{s['code']}-{s.get('variant') or ''}".rstrip("-")
        m = mechs.setdefault(mid, {"key": mid, "code": s["code"], "variant": s.get("variant") or "", "name": s.get("name"), "tons": s.get("tons"), "cls": s.get("cls"),
                                   "faction": s.get("faction"), "pros": s.get("pros"), "cons": s.get("cons"),
                                   "games": 0, "wins": 0, "losses": 0, "scores": [], "best": 0, "medals": [0, 0, 0], "survived": 0, "last": 0, "matches": [],
                                   "since": since_map.get(mid) or since_map.get("*")})
        if m["since"] and (d.get("started") or d.get("saved") or 0) < m["since"]:
            continue                      # before this mech's clean start: listed, not counted
        res = d.get("result", "")
        m["games"] += 1; total["games"] += 1
        if res == "VICTORY": m["wins"] += 1; total["wins"] += 1
        elif res == "DEFEAT": m["losses"] += 1; total["losses"] += 1
        if s.get("score") is not None:
            m["scores"].append(s["score"]); total["score"] += s["score"]
            m["best"] = max(m["best"], s["score"]); total["best"] = max(total["best"], s["score"])
        if s.get("medal"):
            m["medals"][s["medal"] - 1] += 1; total["medals"][s["medal"] - 1] += 1
        if s.get("alive"):
            m["survived"] += 1; total["survived"] += 1
        m["last"] = max(m["last"], d.get("started") or d.get("saved") or 0)
        m["matches"].append({"match_id": d.get("match_id", f[:-5]), "map": d.get("map"), "mode": d.get("mode"), "result": res, "score": s.get("score"), "medal": s.get("medal", 0), "alive": s.get("alive"), "started": d.get("started") or d.get("saved")})
    out = []
    for m in mechs.values():
        m["avg"] = round(sum(m["scores"]) / len(m["scores"])) if m["scores"] else None
        m["scored"] = len(m["scores"]); del m["scores"]
        m["matches"].sort(key=lambda x: -(x["started"] or 0))
        out.append(m)
    out.sort(key=lambda m: (-m["games"], -m["last"]))
    scored_games = sum(m["scored"] for m in out)
    total["avg"] = round(total["score"] / scored_games) if scored_games else None
    return {"pilot": me, "total": total, "mechs": out}


def _since_map() -> dict:
    m = svc.cfg.get("stats_since") if svc else None
    if isinstance(m, (int, float)) and m:            # the first shape: one moment for the whole board
        return {"*": float(m)}
    return m if isinstance(m, dict) else {}


def _save_cfg():
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(svc.cfg, f, indent=2)


@app.post("/api/mymechs/reset")
async def reset_my_mech(body: dict):
    """A clean start for one mech: its stats count from now on. The match records stay."""
    mech = str(body.get("mech") or "").strip()
    if not mech:
        return {"error": "which mech?"}
    m = _since_map(); m[mech] = time.time(); svc.cfg["stats_since"] = m
    _save_cfg()
    svc.records_v = getattr(svc, "records_v", 0) + 1
    return {"mech": mech, "since": m[mech]}


@app.post("/api/mymechs/restore")
async def restore_my_mech(body: dict):
    """Undo one mech's reset: every record counts again for it."""
    mech = str(body.get("mech") or "").strip()
    m = _since_map(); m.pop(mech, None); svc.cfg["stats_since"] = m
    _save_cfg()
    svc.records_v = getattr(svc, "records_v", 0) + 1
    return {"mech": mech, "since": None}


@app.get("/api/records/{match_id}")
def record(match_id: str):
    p = os.path.join(RECORDS, os.path.basename(match_id) + ".json")
    if not os.path.exists(p):
        return {"error": "no such record"}
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


@app.delete("/api/records/{match_id}")
def delete_record(match_id: str):
    n = 0
    for ext in (".jpg", ".json"):
        p = os.path.join(RECORDS, os.path.basename(match_id) + ext)
        if os.path.exists(p):
            os.remove(p); n += 1
    if svc:
        svc.records_v = getattr(svc, "records_v", 0) + 1
    return {"removed": n}


@app.get("/api/assets")
def assets():
    """The pictures that exist, so the page never requests one that does not."""
    out = {}
    for sub in ("mechs", "maps", "mechs/cut"):
        d = os.path.join(ASSETS, sub)
        out[sub] = [f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))] if os.path.isdir(d) else []
    return {"files": out["mechs"], "maps": out["maps"], "cut": out["mechs/cut"]}


@app.get("/api/config")
def get_config():
    return svc.cfg


@app.post("/api/config")
async def set_config(body: dict):
    svc.cfg.update({k: v for k, v in body.items() if not k.startswith("_")})
    from .match import set_panel_region
    set_panel_region(svc.cfg.get("panel_region"))
    _save_cfg()
    return svc.cfg


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    seen = -1
    try:
        while True:
            if svc and svc.version != seen:
                seen = svc.version
                await sock.send_text(json.dumps(svc.payload()))
            await asyncio.sleep(0.15)
    except WebSocketDisconnect:
        pass


@app.middleware("http")
async def _no_stale_static(request, call_next):
    """Browsers must revalidate the page's files on every load, so a fix shows up at once."""
    resp = await call_next(request)
    if request.url.path.startswith(("/static/", "/records/")) or request.url.path in ("/", "/setup", "/calib"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


os.makedirs(RECORDS, exist_ok=True)
app.mount("/records", StaticFiles(directory=RECORDS), name="records")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")
app.mount("/static", StaticFiles(directory=WEB), name="static")
