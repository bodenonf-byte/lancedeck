# LanceDeck — progress and next steps

Kept up to date at the end of each working session. Newest first.

## State on 2026-09-17

**Released:** v0.9.4 (2026-09-15) — build-guide link fix, QUIT button, faster and safer
startup. Unsigned: the SignPath Foundation application (submitted 2026-09-12) is still
unanswered, so the repo has no signing secrets yet.

**On `main`, unreleased (goes into 0.9.5):**

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
