"""Backup, share and import of match records: signed bundles.

A bundle is a zip: records/<id>.json and .jpg, manifest.json (a SHA-256 per file, the pilot,
the app version, the export time, the public key) and manifest.sig (Ed25519 over the manifest
bytes).  A BACKUP also carries identity.json (the private key) and the per-mech reset dates,
so a fresh install restores as the same pilot.  A SHARE bundle has no key: a friend imports it
as your records, read-only, tagged with your name and your key's fingerprint.

What this proves, and what it does not.  A bundle that verifies was not touched since its owner
exported it, and it came from whoever holds that key.  It does not prove the records are true:
the owner holds the key and the code is public.  Foreign records therefore also get a picture
check, the end screen re-read and compared to the JSON, in the background after the import.

The key pair lives in identity.json next to config.json.  It is made the first time it is needed.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import time
import zipfile

from .paths import ROOT, RECORDS, VERSION

IDENTITY = os.path.join(ROOT, "identity.json")
FORMAT = "lancedeck-records/1"
MAX_BUNDLE = 800 * 1024 * 1024


# ── keys ─────────────────────────────────────────────────────────────────────────────

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def fingerprint(public_b64: str) -> str:
    """A1B2-C3D4-E5F6: the first six bytes of the public key's SHA-256, easy to read out loud."""
    h = hashlib.sha256(_unb64(public_b64)).hexdigest().upper()[:12]
    return "-".join(h[i:i + 4] for i in range(0, 12, 4))


def load_identity() -> dict | None:
    if not os.path.exists(IDENTITY):
        return None
    try:
        with open(IDENTITY, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("private") and d.get("public"):
            return d
    except Exception:
        pass
    return None


def ensure_identity(pilot: str = "") -> dict:
    """The local key pair, made on first use."""
    d = load_identity()
    if d:
        return d
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    d = {"_about": "LanceDeck signing key. It signs your record backups and exports so they can be checked. "
                   "Keep it private: whoever has it can sign records as you. A BACKUP includes it.",
         "pilot": pilot,
         "private": _b64(priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())),
         "public": _b64(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
         "created": time.time()}
    _write_identity(d)
    return d


def _write_identity(d: dict):
    with open(IDENTITY, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def _sign(private_b64: str, data: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return _b64(Ed25519PrivateKey.from_private_bytes(_unb64(private_b64)).sign(data))


def _verify(public_b64: str, sig_b64: str, data: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(_unb64(public_b64)).verify(_unb64(sig_b64), data)
        return True
    except Exception:
        return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-") or "pilot"


# ── records on disk ───────────────────────────────────────────────────────────────────

def is_foreign(rec: dict) -> bool:
    """An imported record from another pilot's bundle: shown, never counted as yours."""
    return isinstance(rec.get("origin"), dict)


def own_record_ids() -> list[str]:
    if not os.path.isdir(RECORDS):
        return []
    out = []
    for f in sorted(os.listdir(RECORDS)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(RECORDS, f), encoding="utf-8") as fh:
                if not is_foreign(json.load(fh)):
                    out.append(f[:-5])
        except Exception:
            continue
    return out


def summary(cfg: dict) -> dict:
    """What the page shows beside the buttons: whose key this is, how many records of each kind."""
    ident = load_identity()
    own = foreign = 0
    if os.path.isdir(RECORDS):
        for f in os.listdir(RECORDS):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(RECORDS, f), encoding="utf-8") as fh:
                    foreign_ = is_foreign(json.load(fh))
            except Exception:
                continue
            if foreign_: foreign += 1
            else: own += 1
    return {"pilot": cfg.get("my_name") or "", "fingerprint": fingerprint(ident["public"]) if ident else None,
            "created": ident.get("created") if ident else None, "own": own, "imported": foreign}


# ── export ────────────────────────────────────────────────────────────────────────────

def export_bundle(cfg: dict, with_key: bool) -> tuple[str, bytes]:
    """The zip and its file name.  with_key = a BACKUP (identity + reset dates travel along);
    without = a SHARE bundle for someone else."""
    pilot = cfg.get("my_name") or ""
    ident = ensure_identity(pilot)
    files: dict[str, bytes] = {}
    for mid in own_record_ids():
        for ext in (".json", ".jpg"):
            p = os.path.join(RECORDS, mid + ext)
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    files[f"records/{mid}{ext}"] = fh.read()
    manifest = {"format": FORMAT, "app": VERSION, "pilot": pilot, "exported": time.time(),
                "public_key": ident["public"], "kind": "backup" if with_key else "share",
                "records": sum(1 for k in files if k.endswith(".json")),
                "files": {k: _sha(v) for k, v in files.items()}}
    if with_key:
        manifest["stats_since"] = cfg.get("stats_since") if isinstance(cfg.get("stats_since"), dict) else {}
    body = _canonical(manifest)
    sig = _sign(ident["private"], body)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", body)
        z.writestr("manifest.sig", sig)
        if with_key:
            z.writestr("identity.json", json.dumps({k: v for k, v in ident.items() if not k.startswith("_")}, indent=2))
        z.writestr("README.txt", _readme(manifest))
        for k, v in files.items():
            z.writestr(k, v, compress_type=zipfile.ZIP_STORED if k.endswith(".jpg") else zipfile.ZIP_DEFLATED)
    day = time.strftime("%Y-%m-%d")
    name = f"LanceDeck-{'backup' if with_key else 'records'}-{_slug(pilot)}-{day}.zip"
    return name, buf.getvalue()


def _readme(m: dict) -> str:
    return (f"LanceDeck {m['kind']} of {m['records']} match records by {m['pilot'] or 'a pilot'}, "
            f"exported {time.strftime('%Y-%m-%d %H:%M', time.localtime(m['exported']))} with LanceDeck {m['app']}.\n"
            f"Key fingerprint: {fingerprint(m['public_key'])}\n\n"
            "Import it from the RECORDS view (IMPORT button). manifest.json lists every file with its SHA-256 and\n"
            "manifest.sig is the owner's Ed25519 signature over it: a changed file fails the import check.\n"
            + ("This is a BACKUP: identity.json is the owner's private signing key. Do not pass it on.\n" if m["kind"] == "backup" else
               "This is a SHARE bundle: it carries no private key and imports as the owner's records, read-only.\n"))


# ── inspect and import ────────────────────────────────────────────────────────────────

def _open(data: bytes) -> tuple[zipfile.ZipFile, dict, dict]:
    """The zip, its manifest, and the verdicts: parse errors raise ValueError with a plain message."""
    if len(data) > MAX_BUNDLE:
        raise ValueError("the file is too big to be a LanceDeck bundle")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
    except Exception:
        raise ValueError("not a zip file")
    if "manifest.json" not in names:
        raise ValueError("no manifest.json inside: not a LanceDeck bundle")
    body = z.read("manifest.json")
    try:
        m = json.loads(body.decode("utf-8"))
    except Exception:
        raise ValueError("manifest.json is not readable")
    if m.get("format") != FORMAT or not isinstance(m.get("files"), dict) or not m.get("public_key"):
        raise ValueError("manifest.json is not a LanceDeck records manifest")
    v = {"signature": False, "hashes": True, "missing": [], "changed": [], "extra": []}
    if "manifest.sig" in names:
        v["signature"] = _verify(m["public_key"], z.read("manifest.sig").decode("ascii", "ignore").strip(), body)
    for k, h in m["files"].items():
        if not re.fullmatch(r"records/[A-Za-z0-9_@~.-]+\.(json|jpg)", k):
            v["extra"].append(k); continue
        if k not in names:
            v["missing"].append(k); v["hashes"] = False; continue
        if _sha(z.read(k)) != h:
            v["changed"].append(k); v["hashes"] = False
    return z, m, v


def inspect_bundle(data: bytes, cfg: dict) -> dict:
    """What the import box shows before anything is written."""
    z, m, v = _open(data)
    ident = load_identity()
    fp = fingerprint(m["public_key"])
    has_key = "identity.json" in z.namelist()
    key_ok = False
    if has_key:
        try:
            k = json.loads(z.read("identity.json").decode("utf-8"))
            key_ok = _sign_check(k, m["public_key"])
        except Exception:
            key_ok = False
    fp_short = fp.split("-")[0]
    existing_own = set(own_record_ids())
    ids = [k[len("records/"):-5] for k in m["files"] if k.endswith(".json")]
    mine = bool(ident) and fingerprint(ident["public"]) == fp
    have = 0
    for mid in ids:
        if mine or has_key:
            have += mid in existing_own
        else:
            have += os.path.exists(os.path.join(RECORDS, f"{mid}@{fp_short}.json"))
    return {"pilot": m.get("pilot") or "", "fingerprint": fp, "exported": m.get("exported"), "app": m.get("app"),
            "kind": m.get("kind") or ("backup" if has_key else "share"),
            "records": len(ids), "pictures": sum(1 for k in m["files"] if k.endswith(".jpg")),
            "already": have, "has_key": has_key and key_ok, "key_broken": has_key and not key_ok,
            "signature": v["signature"], "hashes": v["hashes"], "changed": v["changed"][:8], "missing": v["missing"][:8],
            "same_key": mine, "local_key": fingerprint(ident["public"]) if ident else None,
            "local_pilot": cfg.get("my_name") or ""}


def _sign_check(k: dict, public_b64: str) -> bool:
    """The private key in a backup must be the one behind the manifest's public key."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.from_private_bytes(_unb64(k["private"]))
        pub = _b64(priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        return pub == public_b64
    except Exception:
        return False


def import_bundle(data: bytes, cfg: dict, adopt: bool, allow_unverified: bool) -> dict:
    """Write the records.  adopt = a restore: the records are mine (a backup's key is installed);
    otherwise they are foreign, tagged with the owner's name and fingerprint and queued for the
    picture check.  A bundle whose signature or hashes fail is refused unless allow_unverified."""
    z, m, v = _open(data)
    verified = v["signature"] and v["hashes"]
    if not verified and not allow_unverified:
        raise ValueError("the bundle does not verify: " + ("files changed after export" if not v["hashes"] else "bad or missing signature"))
    fp = fingerprint(m["public_key"])
    fp_short = fp.split("-")[0]
    ident = load_identity()
    same = bool(ident) and fingerprint(ident["public"]) == fp
    names = set(z.namelist())
    installed_key = False
    if adopt and "identity.json" in names and not same:
        k = json.loads(z.read("identity.json").decode("utf-8"))
        if not _sign_check(k, m["public_key"]):
            raise ValueError("the backup's key does not match its manifest")
        k = {kk: vv for kk, vv in k.items() if not kk.startswith("_")}
        k.setdefault("created", time.time()); k["restored"] = time.time()
        _write_identity({"_about": "LanceDeck signing key (restored from a backup). Keep it private.", **k})
        installed_key = True
        same = True
    if adopt and not same:
        raise ValueError("this bundle carries no key: it can only be imported as its owner's records")
    os.makedirs(RECORDS, exist_ok=True)
    written = skipped = 0
    queued: list[str] = []
    cfg_changes: dict = {}
    for k in m["files"]:
        if k in v["missing"] or not k.endswith(".json"):
            continue
        mid = k[len("records/"):-5]
        try:
            rec = json.loads(z.read(k).decode("utf-8"))
            if not isinstance(rec, dict) or not isinstance(rec.get("mine"), list):
                raise ValueError
        except Exception:
            skipped += 1; continue
        jpg = f"records/{mid}.jpg"
        if adopt:
            rec.pop("origin", None); rec.pop("verified", None)
            target = mid
            if os.path.exists(os.path.join(RECORDS, target + ".json")):
                skipped += 1; continue                           # what is here already stays
        else:
            target = f"{mid}@{fp_short}"
            rec["origin"] = {"pilot": m.get("pilot") or "", "fingerprint": fp, "imported": time.time(),
                             "exported": m.get("exported"), "app": m.get("app"), "match_id": mid}
            rec["verified"] = {"signature": verified,
                               "picture": {"verdict": "pending" if jpg in names and jpg not in v["missing"] else "no picture"}}
        with open(os.path.join(RECORDS, target + ".json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False)
        if jpg in names and jpg not in v["missing"]:
            with open(os.path.join(RECORDS, target + ".jpg"), "wb") as fh:
                fh.write(z.read(jpg))
        written += 1
        if not adopt:
            queued.append(target)
    if adopt:
        since = m.get("stats_since")
        if isinstance(since, dict) and since:
            cur = cfg.get("stats_since") if isinstance(cfg.get("stats_since"), dict) else {}
            merged = {**since, **cur}                             # what was set here already wins
            if merged != cur:
                cfg_changes["stats_since"] = merged
        if not cfg.get("my_name") and m.get("pilot"):
            cfg_changes["my_name"] = m["pilot"]
    return {"written": written, "skipped": skipped, "adopted": adopt, "installed_key": installed_key,
            "verified": verified, "pilot": m.get("pilot") or "", "fingerprint": fp, "queued": queued,
            "cfg_changes": cfg_changes}


# ── the picture check ─────────────────────────────────────────────────────────────────

def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def picture_check(mid: str, reader, db, cfg: dict) -> dict | None:
    """Re-read a foreign record's end screen and compare it with its JSON: result, and each
    pilot's score and damage.  Writes the verdict into the record; returns it."""
    jp = os.path.join(RECORDS, mid + ".json"); ip = os.path.join(RECORDS, mid + ".jpg")
    if not os.path.exists(jp):
        return None
    with open(jp, encoding="utf-8") as fh:
        rec = json.load(fh)
    ver = rec.get("verified") if isinstance(rec.get("verified"), dict) else {}
    out = {"verdict": "no picture", "checked": time.time(), "agree": 0, "differ": 0, "notes": []}
    if os.path.exists(ip):
        try:
            from PIL import Image
            from .match import build, detect_map
            img = Image.open(ip).convert("RGB")
            lines = reader.read(img, 1.0)
            raw = build(lines, img, db, cfg, "record")
            if raw.kind != "scoreboard":
                out["verdict"] = "unreadable"; out["notes"].append(f"the picture does not read as a results screen ({raw.kind})")
            else:
                read: dict[str, tuple] = {}
                for s in raw.mine + raw.enemy:
                    if _key(s.pilot):
                        read[_key(s.pilot)] = (s.score, s.damage)
                for side in ("mine", "enemy"):
                    for s in rec.get(side, []):
                        k = _key(s.get("pilot"))
                        got = read.get(k)
                        if got is None and len(k) >= 4:
                            got = next((vv for kk, vv in read.items() if len(kk) >= 4 and (k in kk or kk in k)), None)
                        if got is None:
                            continue
                        for label, mine_, theirs in (("score", s.get("score"), got[0]), ("DMG", s.get("damage"), got[1])):
                            if mine_ is None or theirs is None:
                                continue
                            if mine_ == theirs:
                                out["agree"] += 1
                            else:
                                out["differ"] += 1
                                if len(out["notes"]) < 6:
                                    out["notes"].append(f"{s.get('pilot')}: {label} {mine_} in the record, {theirs} on the picture")
                if raw.result and rec.get("result") and raw.result != rec.get("result"):
                    out["differ"] += 1; out["notes"].insert(0, f"result {rec.get('result')} in the record, {raw.result} on the picture")
                m = raw.map or detect_map([l.text.upper() for l in lines])
                if m and rec.get("map") and m != rec.get("map"):
                    out["notes"].append(f"map {rec.get('map')} in the record, {m} on the picture")
                if out["differ"]:
                    out["verdict"] = "mismatch"
                elif out["agree"] >= 3:
                    out["verdict"] = "ok"
                else:
                    out["verdict"] = "unreadable"; out["notes"].append("too few numbers could be read off the picture to compare")
        except Exception as e:
            out["verdict"] = "unreadable"; out["notes"].append("check failed: " + repr(e)[:120])
    ver["picture"] = out
    rec["verified"] = ver
    with open(jp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False)
    return out
