"""Synthetic screens in the layouts seen on 2026-09-12, so the OCR -> matcher -> roster
pipeline can be exercised without the game.  Run:  python tools/make_fake_tab.py

  tools/fake_tab.png      the TAB scoreboard: CMD / FACTION / PILOT NAME / 'MECH / STATUS /
                          PING columns, your team in three lances with codes, the enemy
                          block with names and STATUS only
  tools/fake_hud.png      the in-play lance panel (BRAVO LANCE: names left, code + DEAD or
                          health % + grid square right) on a noisy background
  tools/fake_target.png   the lance panel plus a target readout naming an enemy mech
"""
import os, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1920, 1080
random.seed(7)
LANCES = {
    "ALPHA":   [("", "mikah j", "JM6-S", "ALIVE"), ("", "dylanpack2", "CRB-27B", "ALIVE"), ("[karl]", "Sling Blade", "KDK-3", "DEAD"), ("[TMEK]", "Evershadow88", "CRB-20", "ALIVE")],
    "BRAVO":   [("", "xRaganx", "KFX-PR", "ALIVE"), ("", "Johnson boulbega", "RVN-4X", "DEAD"), ("", "cardboardcrosshair", "LCT-PB", "ALIVE"), ("", "Lead Storm Hero", "SDR-5V", "DEAD")],
    "CHARLIE": [("", "Innstterrr", "NCT-B", "ALIVE"), ("[PKRL]", "Racoman", "HBK-IIC-A", "ALIVE"), ("", "BlazingLasers", "HBR-F(L)", "DEAD"), ("", "Al Kasai", "ON1-IIC-A", "ALIVE")],
}
ENEMY = [("[WHD-]", "ChromeHoundzer", "ALIVE"), ("[WHD-]", "Demortis Draconis", "DEAD"), ("[WHD-]", "FIREBAAT", "ALIVE"), ("", "JaniceBEngelbrecht1948", "ALIVE"),
         ("[POSM]", "JimCrea", "DEAD"), ("", "kweeph", "ALIVE"), ("", "Loosie", "ALIVE"), ("[-M-]", "Mnexus", "DEAD"),
         ("", "shiromatcha", "ALIVE"), ("[FINC]", "Tw1st3dJ3st3r", "ALIVE"), ("[PBHR]", "Vincent Vascaul", "DEAD"), ("", "Vindow Viper", "ALIVE")]


def font(size, bold=True):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "segoeuib.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def noisy_bg():
    im = Image.new("RGB", (W, H), (60, 70, 66))
    d = ImageDraw.Draw(im)
    for _ in range(400):
        x, y = random.randint(0, W), random.randint(0, H)
        d.ellipse([x, y, x + random.randint(20, 160), y + random.randint(20, 120)], fill=(random.randint(30, 120), random.randint(40, 120), random.randint(30, 100)))
    return im.filter(ImageFilter.GaussianBlur(6))


def scoreboard():
    im = noisy_bg(); d = ImageDraw.Draw(im)
    d.rectangle([160, 40, 1800, 1010], fill=(18, 22, 26))
    d.text((180, 55), "SCOREBOARD", fill=(220, 225, 230), font=font(34))
    hf = font(20)
    for x, t in ((430, "CMD"), (560, "FACTION"), (780, "PILOT NAME"), (1140, "'MECH"), (1400, "STATUS"), (1600, "PING"), (1700, "MUTE")):
        d.text((x, 120), t, fill=(200, 205, 210), font=hf)
    f = font(21); y = 165
    for lance, rows in LANCES.items():
        d.text((430, y), lance, fill=(220, 225, 230), font=f)
        for tag, name, code, status in rows:
            d.rectangle([420, y - 5, 1790, y + 28], fill=(30, 34, 40))
            if tag: d.text((680, y), tag, fill=(200, 205, 210), font=f)
            d.text((780, y), name, fill=(235, 238, 242), font=f)
            d.text((1140, y), code, fill=(235, 238, 242), font=f)
            d.text((1400, y), status, fill=(235, 238, 242) if status == "ALIVE" else (230, 90, 80), font=f)
            d.text((1600, y), str(random.randint(20, 300)), fill=(235, 238, 242), font=f)
            y += 34
        y += 6
    y += 40
    for tag, name, status in ENEMY:
        d.rectangle([420, y - 5, 1790, y + 28], fill=(30, 34, 40))
        if tag: d.text((680, y), tag, fill=(200, 205, 210), font=f)
        d.text((780, y), name, fill=(235, 238, 242), font=f)
        d.text((1400, y), status, fill=(235, 238, 242) if status == "ALIVE" else (230, 90, 80), font=f)
        d.text((1600, y), str(random.randint(20, 300)), fill=(235, 238, 242), font=f)
        y += 34
    im.save(os.path.join(HERE, "fake_tab.png"))


def hud(target=False):
    im = noisy_bg(); d = ImageDraw.Draw(im)
    d.rectangle([90, 40, 560, 230], fill=(24, 40, 44))
    d.text((140, 50), "BRAVO LANCE", fill=(90, 230, 200), font=font(22))
    names = [("Johnson boulbega", True), ("cardboardcrosshair", False), ("xRaganx", False), ("Lead Storm Hero", True)]
    y = 85
    for n, dead in names:
        d.text((130, y), n, fill=(230, 70, 60) if dead else (110, 235, 200), font=font(21)); y += 27
    codes = [("RVN-4X DEAD", True), ("LCT-PB 93%  E5", False), ("KFX-PR 56%  D5", False), ("SDR-5V DEAD", True)]
    y = 110
    for c, dead in codes:
        d.text((560, y), c, fill=(230, 70, 60) if dead else (110, 235, 200), font=font(20)); y += 26
    # Q-overlay tags: health + distance, name, (title), CHASSIS CODE — blue friend, red enemy
    for x, y, col, hp, dist, name, title, mech in ((700, 480, (120, 170, 255), "100%", "180m", "Innstterrr", None, "NOVA CAT NCT-B"),
                                                  (1500, 520, (235, 80, 70), "72%", "410m", "Loosie", "The Raptor", "ATLAS AS7-D")):
        d.text((x - 90, y + 4), hp, fill=col, font=font(17)); d.text((x - 90, y + 24), dist, fill=col, font=font(17))
        d.text((x, y), name, fill=col, font=font(19)); yy = y + 22
        if title: d.text((x, yy), title, fill=col, font=font(17)); yy += 20
        d.text((x, yy), mech, fill=col, font=font(19))
    if target:
        d.rectangle([1380, 300, 1760, 420], fill=(24, 40, 44))
        d.text((1400, 310), "ChromeHoundzer", fill=(230, 90, 80), font=font(20))
        d.text((1400, 345), "TIMBER WOLF", fill=(230, 90, 80), font=font(22))
        d.text((1400, 380), "TBR-PRIME", fill=(230, 90, 80), font=font(20))
    im.save(os.path.join(HERE, "fake_target.png" if target else "fake_hud.png"))


DROP_MINE = [("ALPHA", "", "TeheranEuroclydon", "DWF-UV", "READY"), ("", "[SROM]", "Turn Or Burn", "CRB-20", "READY"), ("", "", "MrLowKey", "MAD-B", "READY"), ("", "", "IMlartillery", "TBR-C", "READY"),
             ("BRAVO", "", "Arxael1975", "", "CONNECTING..."), ("", "[FLNK]", "Lieutenant General Zambologist", "FMT-PRIME", "READY"), ("", "", "Johnson boulbega", "RVN-4X", "NOT READY"), ("", "[FLNK]", "Dr Zambolgist PHDMD", "FMT-AL", "NOT READY"),
             ("CHARLIE", "", "KusokawaParty", "MDD-BA", "READY"), ("", "", "T1er5Ace", "HBK-IIC-A", "READY"), ("", "[CJL]", "Slinky9977", "RFL-IIC-2", "READY"), ("", "[(99)]", "Ristand", "NVA-PRIME", "READY")]
DROP_ENEMY = [("", "absolutemenace", "READY"), ("[RIMS]", "Arson71", "READY"), ("", "Christ33AD", "READY"), ("[CI]", "Daemondym", "READY"), ("[CI]", "Ihasa", "READY"), ("", "jolly lobber", "READY"),
              ("", "M A C E", "CONNECTING..."), ("[CI]", "Noonan", "READY"), ("[LORS]", "Old Dice Roller", "NOT READY"), ("", "Suckatash Blitz", "NOT READY"), ("[MIEL]", "Tiberius Vanhaller", "READY"), ("[CI]", "TwigTech", "NOT READY")]


def drop():
    im = noisy_bg(); d = ImageDraw.Draw(im)
    d.text((110, 30), "DROP PREPARATION", fill=(235, 238, 242), font=font(40))
    d.rectangle([110, 90, 1200, 540], fill=(18, 22, 26)); d.rectangle([1230, 90, 1960, 540], fill=(18, 22, 26))
    d.text((200, 100), "Your Team", fill=(80, 160, 255), font=font(30)); d.text((1320, 100), "Your Enemy", fill=(240, 60, 60), font=font(30))
    hf = font(18)
    for x, t in ((220, "CMD"), (290, "FACTION"), (395, "PILOT NAME"), (705, "'MECH"), (875, "STATUS"), (1030, "PING")): d.text((x, 165), t, fill=(200, 205, 210), font=hf)
    for x, t in ((1300, "FACTION"), (1400, "PILOT NAME"), (1755, "STATUS"), (1890, "PING")): d.text((x, 165), t, fill=(200, 205, 210), font=hf)
    f = font(19); y = 200
    for lance, tag, name, code, status in DROP_MINE:
        if lance: d.text((140, y), lance, fill=(235, 238, 242), font=f)
        if tag: d.text((315, y), tag, fill=(200, 205, 210), font=f)
        d.text((395, y), name, fill=(235, 238, 242), font=f); d.text((705, y), code, fill=(235, 238, 242), font=f)
        d.text((875, y), status, fill=(90, 220, 90) if status == "READY" else (235, 238, 242), font=f); d.text((1030, y), str(random.randint(10, 250)), fill=(235, 238, 242), font=f)
        y += 28
    y = 200
    for tag, name, status in DROP_ENEMY:
        if tag: d.text((1325, y), tag, fill=(200, 205, 210), font=f)
        d.text((1400, y), name, fill=(235, 238, 242), font=f)
        d.text((1755, y), status, fill=(90, 220, 90) if status == "READY" else (235, 238, 242), font=f); d.text((1890, y), str(random.randint(10, 250)), fill=(235, 238, 242), font=f)
        y += 28
    d.text((135, 580), "GAMEMODE", fill=(235, 238, 242), font=font(26)); d.text((360, 580), "CONQUEST", fill=(250, 189, 61), font=font(26))
    d.text((1250, 590), "MAP", fill=(235, 238, 242), font=font(22)); d.text((1250, 620), "HPG MANIFOLD", fill=(250, 189, 61), font=font(24))
    d.text((335, 975), "Welcome to the MWO N. American servers.", fill=(250, 189, 61), font=font(18)); d.text((335, 1005), "Team >   Type a message", fill=(200, 205, 210), font=font(18))
    im.save(os.path.join(HERE, "fake_drop.png"))


END_MINE = [("130 1", "T1er5Ace", "HBK-IIC-A", "ALIVE", "105 0 2 412 93"), ("262", "KusokawaParty", "MDD-BA", "DEAD", "138 0:05 0 4 303 126"),
            ("296 0", "Turn Or Burn", "CRB-20", "ALIVE", "88 1 1 260 31"), ("C5", "Johnson boulbega", "RVN-4X", "DEAD", "70 0:11 0 0 83 244")]
END_ENEMY = [("434", "Old Dice Roller", "JR7-D", "DEAD", "70 0:11 0 0 83 90"), ("131 1", "Suckatash Blitz", "BNC-3E", "ALIVE", "238 1 0 482 81"),
             ("", "Noonan", "KTO-GB", "ALIVE", "20 0 1 120 19"), ("176 1", "TwigTech", "ANH-1E", "DEAD", "89 0 0 44 23")]


def endtable():
    """The end-of-match table as MWO draws it: your team's table left, theirs right, the same
    rows heights; columns PILOT, 'MECH, STATUS, MATCH SCORE, TIME, KILLS, ASSISTS, DAMAGE, PING."""
    im = noisy_bg(); d = ImageDraw.Draw(im)
    d.rectangle([20, 40, 1900, 900], fill=(18, 22, 26))
    d.text((40, 55), "DEFEAT", fill=(230, 90, 80), font=font(40))
    hf = font(14); f = font(19)
    for x0, block in ((30, END_MINE), (1010, END_ENEMY)):
        for dx, t in ((0, "PILOT NAME"), (290, "'MECH"), (430, "STATUS"), (540, "MATCH SCORE"), (660, "TIME"), (730, "K"), (770, "A"), (810, "DAMAGE")):
            d.text((x0 + dx, 120), t, fill=(200, 205, 210), font=hf)
        y = 160
        for i, (lead, name, code, status, tail) in enumerate(block):
            d.text((x0, y), name, fill=(235, 238, 242), font=f)
            d.text((x0 + 290, y), code, fill=(235, 238, 242), font=f)
            d.text((x0 + 430, y), status, fill=(235, 238, 242) if status == "ALIVE" else (230, 90, 80), font=f)
            nums = [lead, f"{i}:{(i * 7) % 60:02d}"] + tail.split()
            for j, n in enumerate(nums):
                d.text((x0 + 540 + j * 56, y), n, fill=(235, 238, 242), font=f)
            y += 30
    im.save(os.path.join(HERE, "fake_end.png"))


def target_panel():
    """The top-right target info panel: weapons on the left, the variant under the paper doll."""
    im = Image.new("RGB", (1030, 400), (8, 12, 16)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([10, 10, 1020, 390], radius=30, outline=(70, 80, 220), width=4)
    f = font(20, False); y = 60
    for w in ("ER SML LASER", "ER SML LASER", "ER SML LASER", "ER MED LASER", "ER MED LASER"):
        d.text((110, y), w, fill=(235, 220, 90), font=f); y += 30
    d.text((470, 270), "Front", fill=(235, 220, 90), font=f); d.text((770, 270), "Rear", fill=(235, 220, 90), font=f)
    d.text((440, 300), "FLEA FLE-20", fill=(235, 220, 90), font=font(22))
    im.save(os.path.join(HERE, "fake_target_panel.png"))


def main():
    scoreboard(); hud(False); hud(True); drop(); endtable(); target_panel()
    print("wrote fake_tab.png fake_hud.png fake_target.png fake_drop.png")


if __name__ == "__main__":
    main()
