# LanceDeck — progress and next steps

Kept up to date at the end of each working session. Newest first.

## State on 2026-09-23

**CPU, second pass (measured on the dev PC, 32 cores, a live match on the 0.9.5-dev build).**
The 2026-09-22 fix works — ONNX spin-wait off is worth 4 cores per read (a full frame reads
in 1.8 s at 4.2 cores busy instead of 1.9 s at 7.2, the lance-panel corner in 0.15 s at 3.0
instead of 0.14 s at 7.2). What was left, at 5.3 cores in a match:

- `SetPriorityClass` **never worked**: `ctypes.windll.kernel32.GetCurrentProcess()` with no
  `restype` hands the pseudo-handle over as a 32-bit int, so the call returned 0 with
  ERROR_INVALID_HANDLE and the helper ran at Normal priority against the game, from the day
  the line was written. With `GetCurrentProcess.restype = c_void_p` and
  `SetPriorityClass.argtypes` it returns 1 and the process reads BelowNormal / base 6. It
  says so on the console when it fails now, instead of passing in silence. Verified on the rebuilt dev exe: it comes
  up BelowNormal / base 6 on its own, and sits at 0.39 cores (1.2 %) with the game in the
  menus. The in-match figure still has to be taken on a real match.
- The panel loop never rested. The 2026-09-22 commit gave the full loop "rest at least half
  the read" and left the panel loop on `sleep(dt - elapsed)`: a tick costs the panel corner
  (~0.2 s) plus, on alternate ticks, the target panel (~0.5 s) against a 0.5 s interval at
  `fps` 2, so it ran back to back all match with four OCR threads pinned — and its Python
  half fought the full loop for the GIL (the same corner that reads in 0.2 s alone was
  taking 0.45-0.64 s live). Same rule as the full loop now.

**Where the rest of the CPU goes, if it has to come down further** (measured, not guessed):
the full 3440x1440 read is 0.25/s x 7.5 core-seconds = 1.9 cores, the panel and target reads
about 1.5, and the remainder is capture, conversion and matching. Inside a full read,
DETECTION is only 0.45 s — 3.0 s is recognising the 118 boxes found, so a smaller
`det_limit_side_len` buys nothing (1280 and 960 read the same 89 texts no faster). The two
levers left both cost a feature: skip the target-panel OCR when no target is up (~0.8 cores,
needs a cheap "is the panel drawn" test), and read the full frame less often while the HUD
is on screen (risks missing a quick TAB or Q peek).

## State on 2026-09-17

**Released:** v0.9.4 (2026-09-15) — build-guide link fix, QUIT button, faster and safer
startup. Unsigned: the SignPath Foundation application (submitted 2026-09-12) is still
unanswered, so the repo has no signing secrets yet.

**On `main`, unreleased (goes into 0.9.5):**

- COMPETITIVE view (2026-09-20): the caster's (spectator client) view of a competitive match.
  `tracker/spectate.py` recognises the two side tables (Health / Player Name / Mech Type / K /
  A, mirrored on the right), the team names and tags, the series banner ("EXD8 - 0"), the
  match score and clock, the Conquest caps (owner from the letter colour) and the HIGHLIGHT
  box (pilot, health, mech, "6 x C-ER MED LASER" lines). `CompRoster` keeps the match across
  frames: health / K / A follow the tables, a loadout sticks to its pilot once read, a new
  roster replaces the old one. `tracker/weapons.py` + `data/weapons.json` sum a loadout into
  alpha, heat, DPS, weighted range and band. `server.analyse()` routes a caster frame there
  and keeps it away from the ordinary roster; `payload()["comp"]` feeds the page. Tested on
  `samples/spectate_001.jpg` (8 v 8, all 16 mechs resolved, the highlighted Executioner's
  three weapon lines read). Not yet tried on a live stream: the highlight box's position and
  the K / A digits (small, often unread on one frame) are the parts to watch.

- Support link (2026-09-20): the SUPPORT button and the About box now open Ko-fi
  (<https://ko-fi.com/johnson_b>) instead of GitHub Sponsors; `config.default.json`, README
  and the article updated. A `config.json` carried over from an older install that still
  holds the old Sponsors URL is treated as unset and gets the Ko-fi link at load time.

- Records vault (28c3ba5): BACKUP / SHARE / IMPORT as signed zip bundles
  (`tracker/vault.py`, Ed25519 via `cryptography`, SHA-256 per file). Imported records are
  read-only, tagged with the owner's name and key fingerprint, never counted on MY MECHS, and
  their end screens are re-read in the background (VERIFIED / PICTURE DIFFERS / UNREADABLE).
  **Not yet tested on real records by the author** — that test is what gates 0.9.5.
- CHECK FOR UPDATES in the About box (dc69518): one request to the GitHub releases API,
  only when the button is pressed; shows the newer release with a GET link, or "you run the
  latest", or "could not reach GitHub". README privacy policy and the article name this
  single on-demand request.

- Mech cut-outs (2026-09-23): a Corsair showed as an empty pad. GrabCut seeds its colour model
  with k-means from OpenCV's global RNG, so the same icon cut differently on every run — six runs
  of COR-7A gave two usable cut-outs and four refusals, and the shipped one was a 26 %-opaque
  fragment. `tools/cut_mech_icons.py` now fixes the seed per attempt, measures each result against
  the icon's own difference from the backdrop (recall of the certain mech, rejection of the certain
  hangar), retries other seeds, and never writes a cut that fails the bar — with no cut-out the page
  falls back to the plain icon, which always shows the mech. `--repair` re-cuts poor cut-outs that
  already exist and moves the hopeless ones to `cut/rejected/`; `--dir` points it at a packaged
  build's assets. Good cuts measure recall 0.70-0.95, broken ones under 0.45, so the bar sits at
  0.55 in the gap: 11 of 1406 failed, 7 re-cut clean (COR-7A 0.40 -> 0.92), 4 fall back to the icon.
  Repaired in the source folder and in both Downloads builds.
- CPU use (2026-09-22): the user saw LanceDeck.exe at 36 % of 32 cores during play. Measured on
  a real frame: 10.3 cores busy, of which two thirds were ONNX Runtime worker threads
  busy-spinning between operators (`allow_spinning` is on by default, three sessions per engine,
  three engines). `tracker/ocr.py` now hands RapidOCR a SessionOptions with spinning off (same
  latency, 3.7 cores); `fps` default 3 -> 2; the full loop rests at least half a read after a slow
  one (the end table is ~2.3 s); both loops throttle to 1/s and 1 per 4 s when nothing match-like
  was read for 30 s (`Service.BUSY_FOR`, `IDLE_FPS`, `IDLE_FULL_EVERY`, `stats.pace`). Live from
  source with the game in the menus: 1.8 cores (5.7 %). **Not yet seen in a real match.**
- Dev build for the CPU check: `Downloads\LanceDeck-v0.9.5-dev-win64` (built 2026-09-22 from
  clean main 64449d1, config/records/assets copied from the 0.9.4 folder, `fps` 2). Game in the
  menus: 2.7 cores (8 %). Once a match confirms the number, 0.9.5 can ship.
- **Uncommitted in the working tree since 2026-09-20:** a caster / competitive-spectator mode
  (`tracker/spectate.py`, `tracker/weapons.py`, `data/weapons.json`, changes in `web/app.js`,
  `web/style.css`, `web/index.html`, and a `_apply_comp` path in `tracker/server.py`). Not in
  any commit; not described anywhere else yet. Finish or shelve it before tagging 0.9.5.
- App icon (2026-09-18): `tools/make_icon.py` draws `web/lancedeck.ico` + `.png` (dark hex
  plate, amber edge, a lance of four mechs in formation); `--icon` in `build/build.ps1` and
  `release.yml`, the tray uses the same picture, the pages link it as favicon. The released
  0.9.4 exe still shows PyInstaller's default icon.

**Field test of 0.9.4:** one match on 2026-09-16 on the released exe; the record saved
cleanly, the end table read all twelve enemy rows with mech, damage and score, no capture
hang.

## 0.9.5 checklist

1. Test the vault on real records: BACKUP, then IMPORT the bundle back (adopt), then a SHARE
   bundle imported as a foreign pilot; check the background verdicts on the imported records.
2. Bump `VERSION` in `tracker/paths.py`, commit, annotated tag `v0.9.5`, push the tag.
   `release.yml` builds a draft with `docs/ARTICLE.md` as body.
3. `gh release edit v0.9.5 --title "LanceDeck 0.9.5" --notes-file <changelog + article>
   --draft=false --latest`. If the release API throws 5xx mid-job: download the
   `LanceDeck-unsigned` workflow artifact, `gh release upload --clobber`, delete the empty
   duplicate drafts by id.
4. Once SignPath answers: repo secrets `SIGNPATH_API_TOKEN`, `SIGNPATH_ORG_ID`,
   `SIGNPATH_PROJECT`, `SIGNPATH_POLICY`, artifact configuration in their portal, then a
   signed release (see `docs/SIGNPATH.md`).

## Open questions

- "Wrong mech info" reported on the HPG Manifold record's podium: the data matched the game's
  own table; the likely cause is the plain MCII-MWK icon shown for the Legend variant
  MCII-MWK(LGD).
- The spectator/chat frame is still classified as a scoreboard now and then (the header
  matcher hits "MECH" in chat text). Harmless but noisy in `sightings.log`.
- Windows blocks the unsigned `python312.dll` from an internet-downloaded zip on some PCs
  ("LoadLibrary: Access is denied"). Unblocking the zip before extracting works around it;
  code signing is the real fix.

## Working notes

- Never restart the helper mid-match. Restart in the lobby, or after a record lands.
- Never run two helpers at once (source `-m tracker` and the exe both grab the same window).
- Mock UI checks: a second uvicorn on another port with `server._build_service = lambda: None`
  and the page opened with `?demo=1`.
