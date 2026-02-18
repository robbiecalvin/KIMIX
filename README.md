# KIMIX

KIMIX is a PyQt5 desktop audio application with three modes:

- `Now Playing`: large visual playback screen
- `Playlist`: queue-style player where users add tracks and play them
- `Editor`: multi-track audio editor with timeline-based clip editing

The app is written in Python and uses `pydub` for editing/export plus `PyQt5` for GUI.

## Screenshots

### Now Playing
![Now Playing](assets/screenshots/nowplaying.png)

### Playlist
![Playlist](assets/screenshots/playlist.png)

### Editor
![Editor](assets/screenshots/editor.png)

## Features

- 3-mode interface: Now Playing / Playlist / Editor
- Add and play local audio tracks in Playlist mode
- Scan a folder to auto-import supported audio files
- Background import/scan with progress + cancel (non-blocking UI)
- Library metadata index (`~/.kimix/library_index.json`) for cached waveform/duration reuse
- Favorites filter and persistent listening session resume
- Optional 1-5s crossfade transition between playlist tracks
- Next-track preloading for faster non-crossfade transitions
- Startup/System Check panel for dependency diagnostics
- Listen history persistence and sleep timer (Now Playing)
- One-click Share Track Info (copies title + source path/URL)
- Background export with progress + cancel (non-blocking UI)
- Undo / Redo for editor operations
- Project-based multi-track editing in Editor mode
- Non-destructive clip source metadata persisted (`source_path`, source ranges, reverse flag)
- Source-based clip reconstruction during playback/export render (fallback to cached clip media if source is unavailable)
- Per-track volume control in editor rows (`-24 dB` to `+12 dB`)
- Per-clip volume control in editor (`-24 dB` to `+12 dB`)
- Cut, copy, paste, delete, split clips
- Drag clips on timeline, snap behavior, track reorder, track rename
- Layered mixing and export
- Playback speed control and optional pitch-change behavior
- Reverse clip to a new row
- Optional splice fades, volume boost, and basic noise reduction
- Microphone recording to a new track row
- Microphone input device selector + live input level meter + optional monitor toggle
- Track mute per row
- Persistent local project autosave (`~/.kimix`)

## Repository

Planned GitHub repository:

- `https://github.com/robbiecalvin/KIMIX`

When available, clone with:

```bash
git clone https://github.com/robbiecalvin/KIMIX.git
cd KIMIX
```

## Requirements

- Python `3.11` or `3.12` (recommended)
  - `pydub` currently depends on `audioop`, which is removed in Python 3.13+
- `ffmpeg` installed and available on `PATH`

## Setup (macOS / Linux)

1. Install Python CLI

```bash
# macOS (Homebrew)
brew install python@3.11

# Linux (example Ubuntu)
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip ffmpeg
```

2. Create and activate a virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Install system audio tools

```bash
# macOS
brew install ffmpeg portaudio

# Linux (if not already installed)
sudo apt install -y ffmpeg portaudio19-dev
```

5. Launch the app

```bash
python audio.py
# or
python -m kimix
```

## Build Standalone App

macOS:

```bash
./scripts/build_macos.sh
```

Windows PowerShell:

```powershell
.\scripts\build_windows.ps1
```

Build output is generated in `dist/` via PyInstaller.

## First Run Diagnostics

Use the `System Check` button in the app header to validate:

- Python version compatibility
- FFmpeg availability
- PyDub import support
- Qt multimedia backend availability
- Mic stack (`numpy` + `sounddevice`)

If required components are missing, KIMIX reports them in plain language.

## Setup (Windows PowerShell)

1. Install Python 3.11 from [python.org](https://www.python.org/downloads/) and ensure `Add python.exe to PATH` is enabled.

2. Create and activate virtual environment

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
```

3. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Install FFmpeg and ensure `ffmpeg.exe` is in your `PATH`.

5. Launch

```powershell
python .\audio.py
# or
python -m kimix
```

## Notes

- If microphone recording is unavailable, install/fix `numpy` + `sounddevice` and system audio libraries.
- If Playlist playback is unavailable, confirm PyQt multimedia backend support in your environment.
- If MP3 or some formats fail to load/export, verify `ffmpeg` is installed and on `PATH`.
- App data is stored in `~/.kimix` (library, playback session, editor projects, history).
- Optional featured catalog source is read from `featured_catalog.json`.
