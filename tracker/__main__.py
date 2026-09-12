"""python -m tracker            start the service on http://localhost:8765
   python -m tracker --once IMG  analyse one screenshot and print the read (no server, no roster)
"""
import json
import os
import sys


def main():
    from .paths import CFG_PATH, CFG_DEFAULT
    if not os.path.exists(CFG_PATH):
        import shutil; shutil.copyfile(CFG_DEFAULT, CFG_PATH)
    cfg = json.load(open(CFG_PATH, encoding="utf-8"))
    if "--port" in sys.argv:
        cfg["port"] = int(sys.argv[sys.argv.index("--port") + 1])
    if len(sys.argv) >= 3 and sys.argv[1] == "--once":
        from PIL import Image
        from .mechdb import MechDB
        from .ocr import Reader
        from .match import build
        img = Image.open(sys.argv[2]).convert("RGB")
        lines = Reader().read(img, float(cfg.get("ocr_scale", 1.0)))
        st = build(lines, img, MechDB(), cfg, "once")
        d = st.as_dict()
        print(f"kind: {st.kind}   ocr lines: {len(lines)}   {st.note}")
        for side in ("mine", "enemy"):
            print(f"== {side} ({len(d[side])})")
            for s in d[side]:
                hp = f"{s['health']}%" if s["health"] is not None else ""
                print(f"  {s['status']:6s} {hp:4s} {s['lance']:7s} {s['cls']:8s} {s['tons']:3d}t {(s['code'] or '?') + ('-' + s['variant'] if s['variant'] else ''):<12s} {s['name']:<16s} {s['pilot']:<24s} conf={s['conf']:.2f}")
        if "--lines" in sys.argv:
            for l in lines: print(f"   [{l.x0:4d},{l.y0:4d}] {l.conf:.2f} {l.text}")
        return
    import uvicorn
    uvicorn.run("tracker.server:app", host="0.0.0.0", port=int(cfg.get("port", 8765)), log_level="warning")


if __name__ == "__main__":
    main()
