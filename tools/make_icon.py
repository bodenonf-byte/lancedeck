"""Draw the LanceDeck icon: a dark hex plate with an amber edge and a lance of four mechs
in formation (four diamonds, the lead one larger).  Writes web/lancedeck.png (256 px, the
tray icon and the browser favicon) and web/lancedeck.ico (16..256, the exe icon).

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

PLATE = (19, 24, 32, 255)        # --panel
EDGE = (250, 189, 61, 255)       # --amber
EDGE_DARK = (150, 105, 25, 255)
AMBER = (250, 189, 61, 255)
AMBER_LIGHT = (255, 224, 140, 255)
CYAN = (77, 216, 216, 255)


def hexagon(cx, cy, r):
    return [(cx + r * math.cos(math.radians(60 * i - 90)), cy + r * math.sin(math.radians(60 * i - 90))) for i in range(6)]


def diamond(cx, cy, w, h):
    return [(cx, cy - h), (cx + w, cy), (cx, cy + h), (cx - w, cy)]


def draw(size):
    """Render at 8x and downsample, so edges stay clean at every size."""
    s = 8
    n = size * s
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = n / 2
    r = n * 0.47
    edge = max(n * 0.055, s * 1.5)
    d.polygon(hexagon(c, c, r), fill=EDGE_DARK)
    d.polygon(hexagon(c, c, r - edge * 0.55), fill=EDGE)
    d.polygon(hexagon(c, c, r - edge), fill=PLATE)

    # the lance: lead mech ahead, two wingmen, one trailing — a diamond of diamonds
    u = n / 64
    lead = (c, c - 13 * u)
    wing_l = (c - 14 * u, c + 1 * u)
    wing_r = (c + 14 * u, c + 1 * u)
    tail = (c, c + 15 * u)
    small = (7 * u, 8.5 * u)
    for (x, y) in (wing_l, wing_r, tail):
        d.polygon(diamond(x, y, *small), fill=AMBER)
    d.polygon(diamond(*lead, 9 * u, 11 * u), fill=AMBER_LIGHT)
    # a cyan status dot on the lead: the "voyant"
    dot = 2.6 * u
    d.ellipse([lead[0] - dot, lead[1] - dot, lead[0] + dot, lead[1] + dot], fill=CYAN)
    return im.resize((size, size), Image.LANCZOS)


def main():
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = {sz: draw(sz) for sz in sizes}
    frames[256].save(os.path.join(WEB, "lancedeck.png"))
    frames[256].save(os.path.join(WEB, "lancedeck.ico"), format="ICO",
                     sizes=[(sz, sz) for sz in sizes],
                     append_images=[frames[sz] for sz in sizes if sz != 256])
    # a preview sheet to eyeball the small sizes
    sheet = Image.new("RGBA", (sum(sizes) + 10 * len(sizes), 256), (40, 40, 40, 255))
    x = 0
    for sz in sizes:
        sheet.paste(frames[sz], (x, 0), frames[sz])
        x += sz + 10
    sheet.save(os.path.join(WEB, "..", "build", "icon_preview.png"))
    print("wrote", os.path.join(WEB, "lancedeck.ico"), "and lancedeck.png")


if __name__ == "__main__":
    main()
