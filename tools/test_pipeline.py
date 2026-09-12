"""End-to-end on the synthetic screens: scoreboard -> lance panel -> target readout, through
the roster, printing what the board would show after each.  Run from the project root:

    .venv\\Scripts\\python.exe tools\\test_pipeline.py
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from PIL import Image
from tracker.mechdb import MechDB
from tracker.ocr import Reader
from tracker.match import build
from tracker.roster import Roster

from tracker.paths import CFG_PATH, CFG_DEFAULT
cfg = json.load(open(CFG_PATH if os.path.exists(CFG_PATH) else CFG_DEFAULT, encoding="utf-8"))
db = MechDB(); reader = Reader(); roster = Roster()


def show(st, label):
    d = st.as_dict()
    print(f"\n== {label}: kind={st.kind} mine={len(d['mine'])} enemy={len(d['enemy'])} {st.note}")
    for side in ("mine", "enemy"):
        for s in d[side]:
            hp = f"{s['health']}%" if s["health"] is not None else ""
            print(f"  {side:5s} {s['status']:6s} {hp:4s} {s['lance']:7s} {s['cls']:8s} {s['tons']:3d}t {(s['code'] or '?') + ('-' + s['variant'] if s['variant'] else ''):<12s} {s['name']:<16s} {s['pilot']}")


ok = True
for name in ("fake_tab.png", "fake_hud.png", "fake_target.png"):
    img = Image.open(os.path.join(HERE, name)).convert("RGB")
    t0 = time.time(); lines = reader.read(img); ms = (time.time() - t0) * 1000
    raw = build(lines, img, db, cfg, name)
    print(f"\n-- {name}: {len(lines)} ocr lines in {ms:.0f} ms -> {raw.kind}, {len(raw.mine)} mine, {len(raw.enemy)} enemy")
    st = roster.merge(raw)
    show(st, "board after " + name)

# the drop-preparation screen, as a NEW match (twelve strangers): it must replace the roster
img = Image.open(os.path.join(HERE, "fake_drop.png")).convert("RGB")
raw = build(reader.read(img), img, db, cfg, "fake_drop.png")
print(f"\n-- fake_drop.png: {raw.kind}, {len(raw.mine)} mine, {len(raw.enemy)} enemy, map={raw.map}, mode={raw.mode}, {raw.note}")
st_drop = roster.merge(raw)
show(st_drop, "board after fake_drop.png")
dd = st_drop.as_dict(); dmine = {s["pilot"].lower(): s for s in dd["mine"]}
drop_checks = [
    ("drop: 12 teammates read from the left table", len(dd["mine"]) == 12),
    ("drop: 12 enemies read from the right table", len(dd["enemy"]) == 12),
    ("drop: Fire Moth FMT-PRIME read", dmine.get("lieutenant general zambologist", {}).get("code") == "FMT"),
    ("drop: Johnson is a Raven, NOT READY counts as alive", dmine.get("johnson boulbega", {}).get("code") == "RVN" and dmine.get("johnson boulbega", {}).get("alive") is True),
    ("drop: the connecting pilot without a mech is still on my team", "arxael1975" in dmine),
    ("drop: map HPG Manifold and mode CONQUEST", raw.map == "HPG Manifold" and raw.mode == "CONQUEST"),
]
print()
for label, passed in drop_checks:
    print(("PASS " if passed else "FAIL ") + label); ok &= passed
# frozen: a nameless enemy sighting after the drop roster goes to the seen pool, not the team
img = Image.open(os.path.join(HERE, "fake_target.png")).convert("RGB")
st_frozen = roster.merge(build(reader.read(img), img, db, cfg, "fake_target.png"))
fz = st_frozen.as_dict()
print(); print(("PASS " if fz["frozen"] else "FAIL ") + "frozen after a full drop read"); ok &= bool(fz["frozen"])
print(("PASS " if len(fz["enemy"]) == 12 and len(fz["mine"]) == 12 else "FAIL ") + f"frozen: still 12 v 12 after a HUD frame with sightings ({len(fz['mine'])} v {len(fz['enemy'])})"); ok &= len(fz["enemy"]) == 12 and len(fz["mine"]) == 12
# the target info panel: the locked mech's weapons land on the one seat that drives it
from tracker.match import target_panel
tp = Image.open(os.path.join(HERE, "fake_target_panel.png")).convert("RGB")
raw_tp = target_panel(reader.read(tp), tp, db)
print(); print(("PASS " if raw_tp.kind == "target" and raw_tp.enemy and raw_tp.enemy[0].code == "FLE" and len(raw_tp.enemy[0].loadout) == 5 else "FAIL ") + f"target panel: FLE-20 with 5 weapons ({raw_tp.enemy[0].loadout if raw_tp.enemy else raw_tp.kind})")
ok &= raw_tp.kind == "target" and bool(raw_tp.enemy) and raw_tp.enemy[0].code == "FLE" and len(raw_tp.enemy[0].loadout) == 5
# the end table read twice over a full drop roster: no growth, enemies stay enemies
before_m, before_e = len(dd["mine"]), len(dd["enemy"])
img = Image.open(os.path.join(HERE, "fake_end.png")).convert("RGB")
for _ in range(2):
    raw = build(reader.read(img), img, db, cfg, "fake_end.png"); st_end = roster.merge(raw)
de = st_end.as_dict(); emine = {s["pilot"].lower(): s for s in de["mine"]}; eenemy = {s["pilot"].lower(): s for s in de["enemy"]}
end_checks = [
    ("end table: my side did not grow past the drop roster", len(de["mine"]) <= max(12, before_m)),
    ("end table: enemy side did not grow past the drop roster", len(de["enemy"]) <= max(12, before_e)),
    ("end table: Suckatash Blitz stays an enemy, now a Banshee", eenemy.get("suckatash blitz", {}).get("code") == "BNC"),
    ("end table: T1er5Ace (read as '130 1 T1er5Ace') matched my pilot", "t1er5ace" in emine and emine["t1er5ace"].get("code") == "HBKIIC"),
    ("end table: KusokawaParty dead", emine.get("kusokawaparty", {}).get("alive") is False),
    ("end table: Johnson dead, still mine", emine.get("johnson boulbega", {}).get("alive") is False),
    ("end table: medals given (SCORE column present)", any(s.get("medal") for s in de["mine"] + de["enemy"])),
]
print()
for label, passed in end_checks:
    print(("PASS " if passed else "FAIL ") + label); ok &= passed
# back to the first match's board for the remaining checks
roster.__init__()
for name in ("fake_tab.png", "fake_hud.png", "fake_target.png"):
    img = Image.open(os.path.join(HERE, name)).convert("RGB"); st = roster.merge(build(reader.read(img), img, db, cfg, name))

d = st.as_dict()
mine = {s["pilot"].lower(): s for s in d["mine"]}
checks = [
    ("12 teammates", len(d["mine"]) == 12),
    ("12 enemies + no duplicate from the target", len(d["enemy"]) == 12),
    ("Johnson dead from the scoreboard and the panel", mine.get("johnson boulbega", {}).get("alive") is False),
    ("cardboardcrosshair 93% from the panel", mine.get("cardboardcrosshair", {}).get("health") == 93),
    ("xRaganx 56%", mine.get("xraganx", {}).get("health") == 56),
    ("Sling Blade dead from the scoreboard only", mine.get("sling blade", {}).get("alive") is False),
    ("ChromeHoundzer's mech is the Timber Wolf from the target readout", next((s for s in d["enemy"] if s["pilot"].lower() == "chromehoundzer"), {}).get("code") == "TBR"),
    ("Hunchback IIC read as HBKIIC", mine.get("racoman", {}).get("code") == "HBKIIC"),
    ("Hellbringer (L) read", mine.get("blazinglasers", {}).get("code") == "HBR"),
    ("Q tag (blue): Innstterrr's health 100% from the overlay", mine.get("innstterrr", {}).get("health") == 100),
    ("Q tag (red): Loosie, an enemy name from the scoreboard, now an Atlas at 72%", next((s for s in d["enemy"] if s["pilot"].lower() == "loosie"), {}).get("code") == "AS7" and next((s for s in d["enemy"] if s["pilot"].lower() == "loosie"), {}).get("health") == 72),
]
print()
for label, passed in checks:
    print(("PASS " if passed else "FAIL ") + label); ok &= passed
print("\nPIPELINE_OK" if ok else "\nPIPELINE_FAILED")
