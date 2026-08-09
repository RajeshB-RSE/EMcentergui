# EMControl GUI

Standalone control panel for an ETS-Lindgren EMCenter chassis (mast /
turntable positioners only). One-click preset moves, connect/disconnect
with a live status indicator, manual move + jog, speed control, and a
limit-to-limit scan.

## Files

- `main.py` -- the GUI (customtkinter). Chosen over PySide6 because it
  only needs itself + `darkdetect` + `packaging`, all small pure-Python
  wheels -- much easier on an air-gapped machine than PySide6, which
  additionally needs the large `PySide6-Essentials` and
  `PySide6-Addons` wheels. `main_pyside6.py` is kept in this folder as
  the original PySide6 version if you get those wheels later and
  prefer it.
- `EMCenter.py` -- your driver, unchanged except `connect()` now
  defaults to PyVISA's pure-Python backend (`@py`) instead of NI-VISA,
  so the built app doesn't need any VISA driver installed on the Mac.
- `config.json` -- the **bundled default** axes/presets/limits. Only
  used to seed the real, user-editable copy on first run (see below).
- `requirements.txt` -- Python packages needed
- `build_mac.sh` -- builds a double-click `EMControl.app`

## Where settings actually live (standalone app)

Editing `config.json` inside a packaged `.app` wouldn't stick --
PyInstaller's `--onefile` mode extracts the bundle to a temp folder
that's thrown away after each run. So the app now uses two files
outside the bundle, in a stable location:

```
~/Library/Application Support/EMCenter/config.json   <- axes, presets, limits, default speed
~/Library/Application Support/EMCenter/settings.json <- last-used IP, last speed per axis (auto-saved)
```

- `config.json` there is created automatically on first launch, copied
  from the one bundled in the app. **Edit that copy** (not the one in
  this folder) to change presets/limits after you've built the app --
  changes take effect next launch. To reset to defaults, just delete
  that file and relaunch; it'll be reseeded.
- `settings.json` is written automatically whenever you connect
  successfully (saves the IP) or click a speed's **Set** button (saves
  that axis's speed) -- nothing to edit by hand.
- When running unpackaged (`python3 main.py` straight from this
  folder), the same two files are used, so behavior is identical to
  the built app.

## Offline install checklist (air-gapped Mac)

Based on what installed and what didn't in your `pip list`, on a
machine WITH internet, download these into your `Pyl` wheel folder
(then copy the folder over):

```bash
pip download --no-deps --dest ./Pyl \
    customtkinter darkdetect packaging \
    pyvisa pyvisa-py python-vxi11 standard-xdrlib \
    setuptools pyinstaller pyinstaller-hooks-contrib altgraph macholib
```

You already have: `customtkinter`, `darkdetect`, `packaging`, `pyvisa`,
`standard-xdrlib`. Still needed: `pyvisa-py`, `python-vxi11`,
`setuptools` (this is what made `pyinstaller` fail), plus
`pyinstaller`'s own dependencies (`altgraph`, `macholib`,
`pyinstaller-hooks-contrib`) which you already partially have.

`python-vxi11` has no wheel (only an old `.egg` and a `.tar.gz`
source dist) -- `pip download` will grab the `.tar.gz`, and
`pip install --no-index --find-links` can install directly from that
as long as `setuptools` is present in the venv, which is why getting
`setuptools` in first matters.

You do **not** need `PySide6`, `PySide6_Essentials`, `PySide6_Addons`,
or `shiboken6` for the customtkinter build -- skip those.

## 1. Run it directly first (to test before packaging)

```bash
cd emcontrol_gui
python3 -m venv venv
source venv/bin/activate
pip install --no-index --find-links /Users/rse/Desktop/Trial/Pyl -r requirements.txt
python3 main.py
```

(Drop `--no-index --find-links ...` and just use plain
`pip install -r requirements.txt` if this machine has internet
access.)

Enter the chassis IP (pre-filled with the last one you used, or the
config default on first run), click Connect. The dot turns green and
the status reads "Connected successfully" once `*IDN?` responds.

## 2. Editing presets / axes / limits

Edit `~/Library/Application Support/EMCenter/config.json` (see above --
NOT the `config.json` in this folder once the app has run at least
once). Each axis entry is:

```json
{
  "name": "Mast 1A (Vertical)",
  "slot": 1,
  "device": "A",
  "kind": "tower",
  "unit": "cm",
  "presets": [100, 250, 375],
  "low_limit": 100,
  "high_limit": 375,
  "default_speed": 4,
  "scan_cycles": 999
}
```

- `kind`: `"tower"` (mast) or `"turntable"` -- changes jog button
  labels (UP/DOWN vs CW/CCW) and controls the layout: all `"tower"`
  axes are placed side by side in one row, everything else
  (turntables) goes in the row(s) below, spanning the same width.
- `presets`: any list of numbers -- one button is created per value.
- `low_limit` / `high_limit`: hard limits for that axis, in the same
  units as `unit`. Pushed to the card (`LL`/`UL`) whenever you click
  **Scan**; manual/preset moves are silently clamped into this range
  before being sent (clamps are logged); and the position readout
  turns **red with a warning** if a polled position is ever outside
  this range. Omit both to leave an axis without limits -- its Scan
  button will be disabled and no color warning will trigger.
- `default_speed`: speed preset (1-8) used the very first time the app
  runs, before any speed has been saved yet. Ignored after that --
  `settings.json` takes over.
- `scan_cycles`: how many limit-to-limit cycles the card runs when you
  hit Scan (uses the card's native `CY` + `SC` scan, not a software
  loop). Defaults to 999 as a "run until stopped" stand-in -- check
  your 7006-001 manual for the actual max the `CY` command accepts, I
  didn't have a hard number to confirm this against. Hit the same
  button (now labeled "Stop Scan") or **STOP** / **STOP ALL** to
  interrupt it at any time.
- Add a new axis (e.g. a second turntable) by adding another object to
  the `axes` list.

Note: your turntable is a non-continuous type with a safe practical
max around 359 deg (per your scan framework notes) -- the default
config uses 359 instead of 360 for that reason. Change it if you've
since confirmed 360 is safe on your hardware.

## 3. Speed control

Each axis panel has a small "Speed:" box pre-filled with `S1`-`S8`
(defaults to `S4` on first run, then remembers whatever you last set).
Type a value and click **Set**:

- Accepts `S1`-`S8` or a plain `1`-`8`.
- Anything else pops up: *"User input speed range is S1-S8."* and is
  ignored -- nothing is sent to the card.
- On success it's sent immediately (`S{n}` command) if connected, and
  saved to `settings.json` either way.
- On every future connect, whatever's currently shown in each speed
  box is automatically re-applied to the card -- so your last speeds
  come back on their own after a relaunch.

## 4. Confirm-before-scan

Clicking **Scan** now shows a confirmation dialog first (axis name,
range, cycle count) before anything is sent to the hardware. Cancel
and nothing happens; confirm and it starts the same limit-to-limit
scan as before.

## 5. Build the standalone Mac app

```bash
chmod +x build_mac.sh
./build_mac.sh
```

This produces `dist/EMControl.app` -- copy that anywhere and
double-click to run. No Python, no NI-VISA driver required.

**Architecture note:** build on the same chip type you'll run it on
(Apple Silicon M-series vs Intel). A PyInstaller build is not
universal across the two unless you build with `--target-arch universal2`
and have universal2 wheels for every dependency, which PySide6/pyvisa
don't reliably provide -- simplest is to just build directly on the
target Mac.

**Gatekeeper note:** since this isn't notarized/signed, macOS may
warn on first launch. Right-click the app -> Open -> Open, once, to
approve it.

### If `./build_mac.sh` doesn't run

Also included: `build_mac.command` -- identical content, just a
different extension, since you mentioned `.command` has worked for
you before. Double-click it in Finder, or run it the same way as the
`.sh` version (`chmod +x build_mac.command && ./build_mac.command`).

If neither runs from Terminal, in rough order of likelihood:

1. **Execute bit didn't actually apply.** Check with `ls -l
   build_mac.sh` -- you want to see `-rwxr-xr-x`, not `-rw-r--r--`.
   If `chmod +x` silently didn't take (rare, but happens on some
   synced/network folders), run the script by handing it to bash
   directly instead, which ignores the execute bit entirely:
   `bash build_mac.sh`

2. **Windows-style line endings (CRLF).** If this file was ever
   opened/saved by a Windows editor or transferred through something
   that rewrites line endings, you'll get `bad interpreter:
   /bin/bash^M: no such file or directory`. Fix with:
   `sed -i '' 's/\r$//' build_mac.sh`

3. **Quarantine flag from download.** Files downloaded via a browser
   get a `com.apple.quarantine` extended attribute, which can block
   double-click execution (mainly affects `.command` via Finder more
   than `./script.sh` via Terminal, but worth ruling out either way):
   `xattr -d com.apple.quarantine build_mac.sh build_mac.command`

4. **Skip the script entirely.** It's just four commands -- paste
   them straight into Terminal one at a time, which sidesteps any
   script-execution issue completely:

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --no-index --find-links /Users/rse/Desktop/Trial/Pyl -r requirements.txt
   pyinstaller --windowed --onefile --name EMControl --collect-all=pyvisa_py --copy-metadata=pyvisa --copy-metadata=pyvisa-py --add-data "config.json:." main.py
   ```

   (Drop the `--no-index --find-links ...` part of the pip line if
   this machine has internet access instead.)

## 5. Polarization (V/H) for towers

Each tower panel now has **V** / **H** buttons plus a live "Pol:"
readout, using your existing `vertical()` / `horizontal()` /
`polarization()` methods (`PV`/`PH`/`P?` commands). Turntable panels
don't get these -- polarization is a tower-only concept.

## 6. Version header

The window title now reads `EMControl v1.0.0`, and there's also a
small `v1.0.0` label directly in the connection bar (visible even if
the title bar isn't). Bump `APP_VERSION` near the top of `main.py`
when you cut a new release.

The main window is now a **CTkTabview** with two tabs: "Manual
Control" (everything you have today) and an "Advanced" placeholder
tab listing your planned additions (timer-based scan, grid scan,
sweep scan, combine scan). It's empty for now -- just there so adding
those later is a matter of building each as its own tab/section
without restructuring the whole window. Ping me when you're ready to
start on any of them.

## 7. Custom app icon

Run `make_icon.sh` with any square PNG (1024x1024 recommended) to
generate `EMControl.icns` using only built-in macOS tools (`sips` +
`iconutil` -- no extra installs):

```bash
chmod +x make_icon.sh
./make_icon.sh path/to/your-logo.png
```

That produces `EMControl.icns` in this folder. `build_mac.sh` /
`build_mac.command` now automatically pick it up if present (via
`--icon=EMControl.icns`) -- no flag to remember, just have the
`.icns` file sitting next to the script before you build. If you
don't have a logo yet, skip this step; the app builds fine without
one (generic icon).

## 8. Config.json "not found" on the second Mac

Nothing was actually broken -- the file is almost certainly there,
just hidden. `~/Library` is hidden from Finder by default on macOS
(unlike on the first Mac, if you'd revealed hidden files there before
without remembering). Two ways to get to it:

- **Finder:** Go menu -> "Go to Folder..." (Cmd+Shift+G) -> paste
  `~/Library/Application Support/EMCenter` -> Enter.
- **Terminal:**
  ```bash
  open ~/Library/Application\ Support/EMCenter
  ```
  or just inspect it directly:
  ```bash
  cat ~/Library/Application\ Support/EMCenter/config.json
  ```

If that path genuinely doesn't exist yet on the second Mac, it means
the app hasn't successfully launched there yet (the folder + file are
created on first run) -- check the app actually opened rather than
silently failing, and that this build includes `config.json` bundled
via `--add-data "config.json:."` (it's in `build_mac.sh` already, but
worth confirming if you used a manual `pyinstaller` command on that
machine instead of the script).

## 9. Windows build (later)

Same `build_mac.sh` steps but run on Windows with:

```
pyinstaller --windowed --onefile --name EMControl --collect-all=pyvisa_py --copy-metadata=pyvisa --copy-metadata=pyvisa-py --add-data "config.json;." main.py
```

(Only difference from the Mac command is `;` instead of `:` in
`--add-data` -- that's a PyInstaller platform quirk. The Application
Support path convention is macOS-specific -- on Windows this would
typically move to `%APPDATA%\EMCenter\` instead; flag it when you're
ready for the Windows build and I'll adjust the path logic.)
