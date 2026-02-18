#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3.11 >/dev/null 2>&1; then
  echo "python3.11 not found. Install Python 3.11 first."
  exit 1
fi

python3.11 -m venv .build-venv
source .build-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller \
  --noconfirm \
  --windowed \
  --name KIMIX \
  --icon Kimix.png \
  --add-data "featured_catalog.json:." \
  audio.py

echo "Build complete: dist/KIMIX.app"
