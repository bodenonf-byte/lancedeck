# LanceDeck: your MechWarrior Online team, live, on a second screen

*A free, unofficial tool. Everything runs on your own computer. Nothing is sent anywhere.*

![Lance setup](https://raw.githubusercontent.com/bodenonf-byte/lancedeck/main/docs/img/lances.png?v=3)

## What it is

LanceDeck is a small program you run next to MechWarrior Online. While you play, it keeps a
web page up to date with what is happening to both teams: who is on your team and on the
enemy's, which mech each pilot drives, who is still alive, how damaged the mechs you have seen
are, and who is winning. At the end of the match it shows the results with gold, silver and
bronze for each team's three best match scores, and it keeps the final screen of every match you play.

You open the page in any browser, on a second monitor or on a phone on the same wifi, and you
never have to alt-tab.

## How it works, in plain words

The game already shows you everything LanceDeck needs. It just reads it faster than you can:

- **The loading screen** lists both teams. LanceDeck reads the 24 pilot names there and seats
  them in their lances. Those seats never move for the rest of the match.
- **The TAB scoreboard** tells it which mech each of your teammates drives, and who is dead.
- **The lance panel** in the top-left corner, read three times a second, gives the health of your
  lance mates and their deaths within a second of them happening.
- **The Q overlay and the target readout** name the enemy mechs you see, so the enemy side fills
  in as the match goes.
- **The target info panel** in the top right, when you lock an enemy, gives its weapons. They are
  written on that enemy's seat and stay there.
- **The results screen** gives every match score, and that is where the medals come from.

It does this with the same technique your phone uses to read text off a photo: it takes a
picture of the game window a few times a second and runs a text recogniser on it, a method
called OCR (optical character recognition). A mech is recognised by its variant code, the
`AS7-D-DC` or `TBR-PRIME` printed next to a pilot's name, which LanceDeck looks up in a list of
every chassis in the game.

That is the whole trick. **It reads pixels.** It does not read the game's memory, it does not
send keystrokes or clicks, it does not talk to the game's servers, and it does not need your
login. It watches the game window only, and reads nothing at all when the game is not on screen.

## What stays on your computer

All of it:

- your pilot name and settings, in a small text file next to the program;
- the final screen of each match and the results as read, in a `records` folder;
- a handful of sample frames of the scoreboard and the results screen, used to improve the
  reader, in a `samples` folder;
- a log of what it read.

There is no account, no upload, no telemetry, no automatic update check. If you delete the
folder, it is gone. The program never opens a network connection except to serve the page to
your own browser, and one request to GitHub when you press CHECK FOR UPDATES in the About box.

The mech pictures and the map backgrounds are yours too: on first run, LanceDeck copies the mech
icons and the loading-screen art out of the game files already installed on your PC. They are
never included in the download and never shared.

## How it is built

Python. Screen capture with Desktop Duplication, text recognition with RapidOCR, an ONNX model
run on the processor by default so the graphics card stays with the game, a small web server
that pushes updates to the page, and a plain web page. It is packaged into one folder with
PyInstaller. Releases are built by GitHub Actions on a clean Windows machine from the public
source, so anyone can check that the download matches the code. Licence GPL-3.0.

## The views

**Lance setup** is the main view: both teams as three lances of four, every mech standing on its
pad with its name, variant, pilot, tonnage, role and health. Your own seat is framed in amber.
Below each team, an overview: tonnage, the weight-class mix as a radar, capabilities like ECM,
jump jets, brawl and sniper, and a short analysis of the composition.

![My mechs](https://raw.githubusercontent.com/bodenonf-byte/lancedeck/main/docs/img/board.png?v=3)

**My mechs** is your own record: every mech you have played, with games, wins and losses,
average and best match score, medals and how often you survived, plus the last results one by
one.

![Records](https://raw.githubusercontent.com/bodenonf-byte/lancedeck/main/docs/img/records.png?v=3)

**Records** keeps every match: the final screen, the result, the map and mode, how many of each
side survived, your own score, and the medal winners. Each record unfolds into the board of that
match. The last five games also remember which pilot drove which mech, so when you meet someone
again their mech shows up as a supposition before you have even seen it.

**Backup and share.** Records live next to the program, so a reinstall would lose them. The
BACKUP button writes one zip with your records, their end screens, your per-mech reset dates and
your signing key; IMPORT it on a fresh install and everything is back, as you. SHARE writes the
same zip without the key, for a friend: they see your records with your name on them, kept apart
from their own. Both are signed with a key made on your computer, so a record edited after the
export fails the check on import, and every imported end screen is re-read to confirm the numbers
on it. What that proves is that the file is as its owner exported it and that the numbers match
the picture, not that the picture is genuine: a determined forger can still fake a screenshot.
For friends keeping score with each other, that is the honest level of trust a local tool can give.

## A few honest limits

- It reads text, so it can misread. A name with a strange font, a number that looks like a
  letter. Deaths and revivals are confirmed on two consecutive readings to keep the board calm.
- It needs the loading screen or one press of TAB to know the teams. Start the program before
  you drop.
- It was built on one PC at 3440 by 1440. Other resolutions should work because everything is
  measured as a fraction of the game window, but a wrong reading is possible and easy to
  report: the sample frames it keeps show exactly what it saw.
- The text recogniser runs on the processor by default, on four threads at low priority, so it
  does not take frames from the game. It can be moved to the graphics card in the settings.

## Getting it

Download the zip, unpack it, run `LanceDeck.exe`. It sits in the system tray and the setup page
opens in your browser: type your pilot name, confirm the game folder, click import. A few minutes later, while it cuts the
mechs out of their hangar backdrops, you are ready to drop.

LanceDeck is free. If it helps you win, there is a Support button in the app (it opens
<https://ko-fi.com/johnson_b>). Donations pay for the time it takes to keep the reader working
through the game's patches.

*LanceDeck is not affiliated with or endorsed by Piranha Games Inc. MechWarrior and BattleTech
are trademarks of their respective owners.*
