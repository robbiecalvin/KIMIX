$ErrorActionPreference = "Stop"

py -3.11 -m venv .build-venv
.\.build-venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --windowed --name KIMIX --icon Kimix.png --add-data "featured_catalog.json;." audio.py

Write-Host "Build complete: dist/KIMIX"
