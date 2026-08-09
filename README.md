# EMControl GUI

Standalone control panel for an ETS-Lindgren EMCenter chassis (mast / turntable positioners). Built with customtkinter.

**Features:**
- Connect/disconnect with a live status indicator
- One-click preset moves plus manual move and jog
- Speed control (S1–S8), remembered across sessions
- Limit-to-limit scan with confirmation prompt
- Polarization control (V/H) for tower axes
- Position warning if a reading falls outside configured limits

## Files

| File | Description |
|---|---|
| `main.py` | GUI application entry point |
| `EMCenter.py` | EMCenter driver (PyVISA, pure-Python backend — no NI-VISA required) |
| `requirements.txt` | Python dependencies |
| `build_mac.sh` / `build_mac.command` | Build a standalone `EMControl.app` |
| `make_icon.sh` | Generate `EMControl.icns` from a PNG logo |

## Settings

The app stores its configuration outside the packaged bundle so edits persist across runs:

```
~/Library/Application Support/EMCenter/config.json    # axes, presets, limits, default speed
~/Library/Application Support/EMCenter/settings.json  # last-used IP and per-axis speed (auto-saved)
```

`config.json` is created automatically on first launch. To reset to defaults, delete it and relaunch.

### Axis configuration

Each axis in `config.json` follows this schema:

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

- `kind`: `"tower"` or `"turntable"` — determines jog labels (UP/DOWN vs CW/CCW) and layout grouping.
- `presets`: list of values; one button is generated per value.
- `low_limit` / `high_limit`: enforced range. Manual and preset moves are clamped to this range; Scan uses it as the sweep range. Omit both to disable limits and the Scan button for that axis.
- `default_speed`: initial speed (1–8) before any speed has been saved.
- `scan_cycles`: number of limit-to-limit cycles per Scan.

## Running from source

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Building the macOS app

```bash
chmod +x build_mac.sh
./build_mac.sh
```

Produces `dist/EMControl.app`. Since the app isn't notarized, macOS may block the first launch — right-click the app, choose Open, then Open again to approve it.

Build on the same chip architecture (Apple Silicon or Intel) you intend to run on.

### Custom icon

```bash
chmod +x make_icon.sh
./make_icon.sh path/to/logo.png
```

Generates `EMControl.icns`, which `build_mac.sh` picks up automatically if present.

## Windows build

```bash
pyinstaller --windowed --onefile --name EMControl --collect-all=pyvisa_py --copy-metadata=pyvisa --copy-metadata=pyvisa-py --add-data "config.json;." main.py
```

(Same as the macOS build, aside from `;` instead of `:` in `--add-data`.)
