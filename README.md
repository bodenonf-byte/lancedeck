# LanceDeck

A free, unofficial team tracker for **MechWarrior Online**. It watches your own screen while
you play and turns the scoreboard, the lance panel, the Q overlay and the target readouts into
a live team composition page: both teams as three lances of four, every mech with its picture,
role and tonnage, who is alive, who is dead, the enemy loadouts you have locked, a who-is-winning
bar, and at the end the results with gold, silver and bronze for the best match scores. Every
match is kept as a record with its final screen.

**It reads pixels and nothing else.** No memory reading, no input injection, no network calls
to the game. Everything it records stays on your computer.

Not affiliated with or endorsed by Piranha Games Inc. MechWarrior and BattleTech are trademarks
of their respective owners. Mech and map pictures are copied out of *your own* game install on
first run and are never redistributed with this app.

## What it looks like

**Lance setup** — both teams as three lances of four, every mech on its pad with pilot, tonnage, role, health and the enemy loadouts you have locked. Your seat is framed in amber, medallists in gold, silver and bronze.

![Lance setup](docs/img/lances.png)

**My mechs** — the mechs you have played, with games, wins, scores, medals and survival out of your records.

![My mechs](docs/img/board.png)

**Records** — every match's final screen, result, survivors, your score and each team's medallists; each record unfolds into the board of that match.

![Records](docs/img/records.png)

## Install

1. Download the latest release zip and unpack it anywhere.
2. Run `LanceDeck.exe`. An icon appears in the system tray and the setup page opens in your browser.
3. Type your pilot name as it shows in game, check the game folder, click **Save & import**.
   The mech icons and map art are copied from your game files and the mechs are cut out of
   their backdrop (a few minutes, once).
4. Play. Keep the page on a second screen or open `http://<this-pc>:8765` on a phone.

**Every time after that**: run `LanceDeck.exe` before you drop. It sits in the system tray, the
icon next to the clock, and the page opens in your browser by itself at `http://localhost:8765`.
Right-click the icon for Open, Setup, Calibrate and Quit. Running it a second time just opens
the page. A shortcut to the exe on the desktop or in the Start menu is the convenient way.

If Windows SmartScreen shows "Windows protected your PC", click **More info** then **Run anyway**: releases are being moved to builds signed through SignPath Foundation (docs/SIGNPATH.md); until then the warning only means Windows does not know the publisher yet.

## If it does not start

- **Extracting the zip takes a few minutes.** It holds about 1,400 files and Windows scans each
  one as it comes out. Wait until Explorer's progress window is gone before running the exe.
- **"Failed to load Python DLL … Access is denied"** means Windows Defender is still checking
  that file. Wait a minute and run the exe again. If it persists, delete the folder and extract
  the zip again, or extract it with 7-Zip.
- **Nothing opens in the browser**: click the tray icon next to the clock, or open
  `http://localhost:8765` yourself.
- **The page says the game is not found**: the game must be running; the tracker looks for its
  window every few seconds and starts reading as soon as it is there.

## What it needs from you in game

Nothing you do not already do. Press **TAB** once at the start so both teams are read (the
loading screen does it too), lock enemies to read their loadout, and stay on the results
screen a couple of seconds at the end so the record is written.

## Views

- **Lance setup**: both teams, Alpha / Bravo / Charlie, mechs standing on their pads, team
  overview with tonnage, class mix and capabilities.
- **My mechs**: every mech you have played, with games, wins, average and best score, medals and
  survival, out of your records.
- **Records**: every match's final screen, results and medal winners, with the board of that
  match; the last five games also remember which pilot drove which mech.
- **Competitive**: for casters and viewers of a competitive match watched from the spectator
  client. Both teams as the caster's side tables show them, live: health bar, pilot, mech, kills
  and assists, with the series score, the match score, the clock and the capture points on
  top. When the caster highlights a pilot, that pilot's weapons are read off the highlight box
  and stay on their card, summed into alpha damage, heat per alpha, sustained DPS, a
  damage-weighted optimal range and its band (brawl / mid / long), and the count of energy,
  ballistic, missile and support weapons; the team header adds up the loadouts read so far.
  Weapon figures come from `data/weapons.json`, approximate and yours to edit.
- **Backup, share, import** (in Records): BACKUP writes a zip of your records, their end screens,
  your per-mech reset dates and your signing key; IMPORT it on a fresh install and everything is
  back, as you. SHARE writes the same without the key: a friend imports it and sees your records
  tagged with your name, never counted on their board. Every bundle is signed (Ed25519) with a
  SHA-256 per file, so a file edited after export fails the import check, and each imported end
  screen is re-read to confirm the numbers. Your key's fingerprint shows beside the buttons; tell
  it to your friends so they can tell your bundles from someone else's. The key is
  `identity.json` next to `config.json`: a backup carries it, a share bundle never does.

## How it is built

Python. Screen capture with Desktop Duplication (`dxcam`), text recognition with RapidOCR, an
ONNX model run on the CPU by default so the GPU stays with the game, a small FastAPI server that
pushes updates to the page over a websocket, and a plain HTML and JavaScript page. It is packaged
into a single folder with PyInstaller. Releases are built by GitHub Actions on a clean Windows
runner from this public source, so anyone can check that the download matches the code.

The pipeline, in order: `tracker/capture.py` finds the game window and grabs frames,
`tracker/ocr.py` reads the text, `tracker/match.py` turns the lines into a scoreboard, lance
panel, Q overlay, target readout or results screen, `tracker/roster.py` keeps the two teams
consistent across reads, `tracker/spectate.py` reads the caster's client instead when that is
what is on screen (with `tracker/weapons.py` summing the loadouts), `tracker/server.py` serves the page and writes the records, and
`web/` is the page.

## Performance

Runs in quiet mode by default: OCR on the CPU at a low priority so the GPU stays with the
game. During a match the lance panel is read twice a second and the whole frame every two
seconds (`fps` and `full_every` in `config.json`); in the MechLab or the lobby, when nothing
match-like has been read for half a minute, both drop to once a second and once every four
seconds until the drop screen or the HUD shows up. With nothing to read (game closed, or on
another window in exclusive fullscreen) it idles at zero. On a 32-core PC a match costs about
three cores; the OCR engine's worker threads no longer busy-wait between operations, which
used to triple that. `ocr_dml: true` moves OCR to the GPU (faster, but it can cost frames).

## Support

The app is free. If it helps you win, a donation keeps it maintained through the game's
patches: the **Support** button in the app, or directly at <https://ko-fi.com/johnson_b>.

## From source

```
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_app.py
```

Build the shareable app with `powershell build\build.ps1`.

## Code signing policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

- Committers and reviewers: [bodenonf-byte](https://github.com/bodenonf-byte)
- Approvers: [bodenonf-byte](https://github.com/bodenonf-byte)
- Releases are built by GitHub Actions from the public source (`.github/workflows/release.yml`)
  and signed by SignPath from the build output; nothing built on a developer's PC is signed.

Privacy policy: this program will not transfer any information to other networked systems
unless specifically requested by the user or the person installing or operating it. It reads
the game window on the local machine and serves a page to the local browser; the one other
network connection it can make is the update check (a single request to the GitHub releases
API), and only when the user presses CHECK FOR UPDATES in the About box.

## Licence

GNU General Public License v3.0. You may use, study, share and improve LanceDeck freely; anyone
who distributes it, or a program built from it, must offer the source under the same licence.
See LICENSE.

## Credits

Lance emblems by Lorc and Delapouite from [game-icons.net](https://game-icons.net), CC BY 3.0.

## Privacy

The helper captures the game window only, keeps a few sample frames of the scoreboard and the
results screen in `samples\` for tuning, the final screen of each match in `records\`, and a
`sightings.log` of what it read. Delete any of them whenever you like. Nothing is uploaded.
