#!/bin/bash
# Build a standalone double-click EMControl.app for macOS.
# Run this ON the Mac you'll use it on (or a Mac of the same chip
# architecture -- Apple Silicon vs Intel builds are not interchangeable).
#
# If you're air-gapped, install requirements.txt first from your local
# wheel folder, e.g.:
#   pip install --no-index --find-links /path/to/wheel/folder -r requirements.txt

set -e

# Always operate from the folder this script lives in -- double-
# clicking a .command file in Finder starts Terminal in your HOME
# directory, not the script's folder, so without this a fresh venv
# and pip install would happen in the wrong place (e.g. ~/venv
# instead of this project's venv).
cd "$(dirname "$0")"
echo "Working in: $(pwd)"

# 1. (Recommended) create a clean virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Build the .app bundle
# --copy-metadata is required for pyvisa/pyvisa-py: PyVISA finds the
# "py" backend at runtime by reading pyvisa-py's installed package
# metadata (its .dist-info), not just by importing the module. Without
# this flag the module is bundled but PyVISA can't "see" it registered,
# producing "Wrapper not found: No package named pyvisa_py" at runtime
# even though the code is right there in the .app.
#
# --icon is optional -- only added if EMControl.icns exists (build one
# with ./make_icon.sh path/to/your-logo.png first).
ICON_ARGS=()
if [ -f "EMControl.icns" ]; then
    ICON_ARGS=(--icon=EMControl.icns)
fi

pyinstaller --windowed --onefile --name EMControl \
    --collect-all=pyvisa_py \
    --copy-metadata=pyvisa \
    --copy-metadata=pyvisa-py \
    --add-data "config.json:." \
    "${ICON_ARGS[@]}" \
    main.py

echo ""
echo "Done. Find the app at: dist/EMControl.app"
echo "Double-click dist/EMControl.app to run it -- no Python install needed."
