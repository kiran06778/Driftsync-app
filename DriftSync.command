#!/bin/bash
# --- DriftSync launcher: double-click in Finder to start the app ---

# Run from this script's own folder, so .env and focusguard.db are found
cd "$(dirname "$0")" || exit 1

# Use a local virtual environment if one exists, otherwise the system Python 3
if [ -x ".venv/bin/python3" ]; then
    PY=".venv/bin/python3"
elif [ -x "venv/bin/python3" ]; then
    PY="venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    echo "Python 3 is not installed. Get Python 3.9 or newer from https://www.python.org/downloads/"
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

# Quick check (under a second). If packages are missing, offer to install them into .venv (first run only)
if ! "$PY" check_setup.py --quiet; then
    if [ ! -d ".venv" ]; then
        echo ""
        read -r -p "Install what DriftSync needs into a local .venv folder now? (about 150 MB) [Y/n] " ans
        if [ -z "$ans" ] || [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
            "$PY" -m venv .venv && .venv/bin/python3 -m pip install --upgrade pip -q \
                && .venv/bin/python3 -m pip install -r requirements.txt && PY=".venv/bin/python3"
        fi
    fi
    if ! "$PY" check_setup.py --quiet; then
        read -n 1 -s -r -p "DriftSync can't start yet (see FIX above). Press any key to close..."
        exit 1
    fi
fi

# Start the app (same as: python3 desktop_app.py)
"$PY" desktop_app.py

# Keep the window open if the app crashed, so the error can be read
if [ $? -ne 0 ]; then
    echo ""
    read -n 1 -s -r -p "DriftSync stopped with an error. Press any key to close..."
fi
