import hashlib
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from pydub import AudioSegment
    PYDUB_IMPORT_ERROR = ""
except Exception as exc:
    AudioSegment = None
    PYDUB_IMPORT_ERROR = str(exc)

try:
    import numpy as np
    import sounddevice as sd
    SD_IMPORT_ERROR = ""
except Exception as exc:
    np = None
    sd = None
    SD_IMPORT_ERROR = str(exc)

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
except Exception:
    QMediaContent = None
    QMediaPlayer = None

SUPPORTED_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}


def _compute_track_waveform(audio_path: str, bins: int = 180) -> list[float]:
    if AudioSegment is None:
        return []
    try:
        seg = AudioSegment.from_file(audio_path)
        samples = seg.get_array_of_samples()
        if not samples:
            return []
        channels = max(1, seg.channels)
        frames = max(1, len(samples) // channels)
        max_amp = float(1 << (8 * seg.sample_width - 1))
        preview = []
        for i in range(bins):
            s = int((i * frames) / bins)
            e = int(((i + 1) * frames) / bins)
            if e <= s:
                e = min(frames, s + 1)
            peak = 0.0
            for frame in range(s, e):
                base = frame * channels
                avg = 0.0
                for ch in range(channels):
                    avg += abs(samples[base + ch])
                peak = max(peak, avg / channels)
            preview.append(min(1.0, peak / max_amp))
        return preview
    except Exception:
        return []


class LibraryImportWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[str], known_paths: set[str], track_index: dict):
        super().__init__()
        self.paths = paths
        self.known_paths = known_paths
        self.track_index = track_index
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            imported = []
            updated_index = dict(self.track_index)
            total = max(1, len(self.paths))
            skipped_duplicates = 0

            for i, raw_path in enumerate(self.paths, start=1):
                if self._cancel:
                    self.finished.emit(
                        {
                            "entries": imported,
                            "index": updated_index,
                            "skipped_duplicates": skipped_duplicates,
                            "canceled": True,
                        }
                    )
                    return

                path = Path(raw_path).expanduser().resolve()
                pstr = str(path)
                pct = int((i / total) * 100)
                self.progress.emit(pct, f"Analyzing {path.name} ({i}/{total})")

                if pstr in self.known_paths:
                    skipped_duplicates += 1
                    continue
                if not path.exists() or not path.is_file() or path.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
                    continue

                stat = path.stat()
                cache_key = pstr
                cached = updated_index.get(cache_key, {})
                waveform = cached.get("waveform", [])
                duration_ms = int(cached.get("duration_ms", 0) or 0)
                mtime_ns = int(cached.get("mtime_ns", 0) or 0)
                size_bytes = int(cached.get("size_bytes", 0) or 0)

                if mtime_ns != int(stat.st_mtime_ns) or size_bytes != int(stat.st_size) or not waveform:
                    waveform = _compute_track_waveform(pstr)
                    if AudioSegment is not None:
                        try:
                            duration_ms = len(AudioSegment.from_file(pstr))
                        except Exception:
                            duration_ms = 0
                    updated_index[cache_key] = {
                        "mtime_ns": int(stat.st_mtime_ns),
                        "size_bytes": int(stat.st_size),
                        "waveform": waveform,
                        "duration_ms": duration_ms,
                    }

                imported.append(
                    {
                        "title": path.stem,
                        "audio": pstr,
                        "art": "",
                        "favorite": False,
                        "waveform": waveform,
                        "duration_ms": duration_ms,
                    }
                )
                self.known_paths.add(pstr)

            self.finished.emit(
                {
                    "entries": imported,
                    "index": updated_index,
                    "skipped_duplicates": skipped_duplicates,
                    "canceled": False,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


def _system_check_rows() -> list[tuple[str, bool, str]]:
    checks = []
    py_ok = (3, 11) <= sys.version_info < (3, 13)
    checks.append(("Python Version", py_ok, f"{sys.version.split()[0]} (required: 3.11 or 3.12)"))
    checks.append(("FFmpeg", shutil.which("ffmpeg") is not None, "Required by pydub for many formats"))
    checks.append(("PyDub", not bool(PYDUB_IMPORT_ERROR), PYDUB_IMPORT_ERROR or "available"))
    checks.append(("Qt Multimedia", QMediaPlayer is not None, "Required for Playlist/Now Playing playback"))
    checks.append(("Mic Stack", (np is not None and sd is not None), SD_IMPORT_ERROR or "numpy + sounddevice available"))
    return checks


class SystemCheckDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KIMIX System Check")
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)

        refresh_btn = QPushButton("Refresh Checks")
        refresh_btn.clicked.connect(self.populate)
        layout.addWidget(refresh_btn, 0, Qt.AlignRight)
        self.populate()

    def populate(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for name, ok, details in _system_check_rows():
            line = QLabel(f"{'PASS' if ok else 'FAIL'}  {name}: {details}")
            color = "#87d995" if ok else "#f6a3a3"
            line.setStyleSheet(f"color:{color}; font-weight:700; padding:6px 0;")
            self.rows_layout.addWidget(line)


class KIMIXPlayer(QWidget):
    mix_changed = pyqtSignal(int)
    playback_state_changed = pyqtSignal(bool)
    library_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.kimix_dir = Path.home() / ".kimix"
        self.library_file = self.kimix_dir / "library.json"
        self.index_file = self.kimix_dir / "library_index.json"
        self.session_file = self.kimix_dir / "player_session.json"
        self.history_file = self.kimix_dir / "history.json"
        self.featured_file = Path(__file__).resolve().parent.parent / "featured_catalog.json"
        self.art_cache_dir = self.kimix_dir / "art_cache"

        self.kimix_dir.mkdir(parents=True, exist_ok=True)
        self.art_cache_dir.mkdir(parents=True, exist_ok=True)
        self._current_index = -1
        self._current_art = QPixmap()
        self._disc_angle = 0
        self._disc_timer = QTimer(self)
        self._disc_timer.setInterval(60)
        self._disc_timer.timeout.connect(self._spin_disc)

        self.mixes = []
        self.track_index = {}
        self.featured_mixes = []
        self.visible_mixes = []
        self._source_mode = "library"
        self._favorites_only = False
        self._import_thread = None
        self._import_worker = None
        self._import_progress = None
        self._import_context = ""
        self._crossfade_in_progress = False
        self._crossfade_timer = QTimer(self)
        self._crossfade_timer.setInterval(60)
        self._crossfade_timer.timeout.connect(self._tick_crossfade)
        self._crossfade_elapsed_ms = 0
        self._crossfade_duration_ms = 0
        self._crossfade_to_actual_index = -1
        self._crossfade_target_volume = 82
        self._preloaded_actual_index = -1

        self.player = QMediaPlayer(self) if QMediaPlayer is not None else None
        self._alt_player = QMediaPlayer(self) if QMediaPlayer is not None else None

        self._build_ui()
        self._apply_style()
        self._bind_player()
        self._load_catalogs()
        self._load_session()
        self._refresh_mix_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 6, 6, 10)
        title = QLabel("KIMIX Playlist")
        title.setObjectName("kimixTitle")
        sub = QLabel("Listening-first mode. Import your music and press play.")
        sub.setObjectName("kimixSub")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)
        self.feature = QLabel("Library ready")
        self.feature.setObjectName("kimixFeature")
        header_layout.addWidget(self.feature)
        root.addWidget(header)

        main_row = QHBoxLayout()
        main_row.setSpacing(14)
        root.addLayout(main_row, 1)

        stage = QFrame()
        stage.setObjectName("kimixStage")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(14, 14, 14, 14)

        top_row = QHBoxLayout()
        now_box = QVBoxLayout()
        lbl = QLabel("NOW PLAYING")
        lbl.setObjectName("kimixNowLabel")
        self.now_title = QLabel("No track loaded")
        self.now_title.setObjectName("kimixNowTitle")
        now_box.addWidget(lbl)
        now_box.addWidget(self.now_title)
        top_row.addLayout(now_box, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.prev_btn = QPushButton("Prev")
        self.prev_btn.clicked.connect(self.play_previous)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.play_next)
        self.share_btn = QPushButton("Share")
        self.share_btn.clicked.connect(self.share_current_track_info)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(82)
        self.volume.valueChanged.connect(self._set_volume)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.share_btn)
        controls.addWidget(QLabel("Volume"))
        controls.addWidget(self.volume)
        self.crossfade_check = QCheckBox("Crossfade")
        self.crossfade_check.setChecked(True)
        controls.addWidget(self.crossfade_check)
        self.crossfade_seconds = QSpinBox()
        self.crossfade_seconds.setRange(1, 5)
        self.crossfade_seconds.setValue(2)
        self.crossfade_seconds.setSuffix(" s")
        controls.addWidget(self.crossfade_seconds)
        top_row.addLayout(controls)
        stage_layout.addLayout(top_row)

        self.disc_label = QLabel()
        self.disc_label.setFixedSize(280, 280)
        self.disc_label.setAlignment(Qt.AlignCenter)
        self.disc_label.setObjectName("kimixDisc")
        stage_layout.addWidget(self.disc_label, 0, Qt.AlignHCenter)

        foot = QHBoxLayout()
        self.status = QLabel("Use Add Tracks or Scan Folder to begin.")
        self.status.setObjectName("kimixStatus")
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("kimixTime")
        foot.addWidget(self.status, 1)
        foot.addWidget(self.time_label)
        stage_layout.addLayout(foot)
        main_row.addWidget(stage, 3)

        list_panel = QFrame()
        list_panel.setObjectName("kimixList")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_head = QHBoxLayout()
        list_title = QLabel("Tracks")
        list_title.setObjectName("kimixListTitle")
        self.count_label = QLabel("0 tracks")
        self.count_label.setObjectName("kimixCount")
        list_head.addWidget(list_title)
        list_head.addStretch(1)
        list_head.addWidget(self.count_label)
        list_layout.addLayout(list_head)

        source_row = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItem("My Library", "library")
        self.source_combo.addItem("Featured", "featured")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_row.addWidget(self.source_combo)
        self.fav_only = QCheckBox("Favorites Only")
        self.fav_only.stateChanged.connect(self._on_favorites_filter)
        source_row.addWidget(self.fav_only)
        list_layout.addLayout(source_row)

        actions = QHBoxLayout()
        self.add_tracks_btn = QPushButton("Add Tracks")
        self.add_tracks_btn.clicked.connect(self.add_tracks)
        self.scan_folder_btn = QPushButton("Scan Folder")
        self.scan_folder_btn.clicked.connect(self.scan_folder)
        self.favorite_btn = QPushButton("Toggle Favorite")
        self.favorite_btn.clicked.connect(self.toggle_favorite_selected)
        actions.addWidget(self.add_tracks_btn)
        actions.addWidget(self.scan_folder_btn)
        actions.addWidget(self.favorite_btn)
        list_layout.addLayout(actions)

        self.mix_list = QListWidget()
        self.mix_list.itemClicked.connect(self._select_item)
        list_layout.addWidget(self.mix_list, 1)
        main_row.addWidget(list_panel, 2)

        if self.player is None:
            self.play_btn.setEnabled(False)
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.share_btn.setEnabled(False)
            self.crossfade_check.setEnabled(False)
            self.crossfade_seconds.setEnabled(False)
            self.status.setText("Playback unavailable: PyQt5 multimedia backend missing.")

    def _apply_style(self):
        self.setStyleSheet(
            """
            QWidget { background:#05070f; color:#e9ecff; }
            QFrame#kimixStage, QFrame#kimixList { border:1px solid rgba(233,236,255,0.12); border-radius:18px; background: rgba(7,12,30,0.66); }
            QLabel#kimixTitle { font-size:22px; font-weight:720; }
            QLabel#kimixSub { color:rgba(233,236,255,0.68); }
            QLabel#kimixFeature { color:rgba(233,236,255,0.56); }
            QLabel#kimixNowLabel { font-size:11px; color:rgba(233,236,255,0.55); letter-spacing:1px; }
            QLabel#kimixNowTitle { font-size:16px; font-weight:650; }
            QLabel#kimixDisc { border-radius:140px; border:1px solid rgba(233,236,255,0.14); background:qradialgradient(cx:0.3, cy:0.2, radius:1.1, fx:0.3, fy:0.2, stop:0 rgba(84,117,255,0.28), stop:0.45 rgba(255,105,192,0.20), stop:0.75 rgba(100,255,210,0.15), stop:1 rgba(0,0,0,0.78)); }
            QPushButton { border:1px solid rgba(84,117,255,0.40); border-radius:10px; padding:7px 11px; background: rgba(84,117,255,0.18); color:#e9ecff; font-weight:700; }
            QListWidget { border:1px solid rgba(233,236,255,0.10); border-radius:12px; background: rgba(255,255,255,0.03); padding:4px; }
            QListWidget::item { border:1px solid rgba(233,236,255,0.10); border-radius:10px; margin:3px; padding:8px; background: rgba(255,255,255,0.03); }
            QListWidget::item:selected { background: rgba(84,117,255,0.18); border:1px solid rgba(84,117,255,0.45); }
            QLabel#kimixStatus { color:rgba(233,236,255,0.75); }
            QLabel#kimixTime { color:rgba(233,236,255,0.85); font-family:monospace; }
            QLabel#kimixListTitle { font-weight:720; }
            QLabel#kimixCount { color:rgba(233,236,255,0.55); font-family:monospace; }
            """
        )

    def _bind_player(self):
        if self.player is None:
            return
        self._disconnect_player_signals(self.player)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.stateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self._duration_ms = 0

    def _disconnect_player_signals(self, player):
        if player is None:
            return
        for signal, slot in [
            (player.positionChanged, self._on_position),
            (player.durationChanged, self._on_duration),
            (player.stateChanged, self._on_state),
            (player.mediaStatusChanged, self._on_media_status),
        ]:
            try:
                signal.disconnect(slot)
            except Exception:
                pass

    def _playlist_file(self) -> Path:
        return self.library_file

    def _load_catalogs(self):
        self.mixes = []
        self.track_index = {}
        if self.index_file.exists():
            try:
                raw_index = json.loads(self.index_file.read_text(encoding="utf-8"))
                self.track_index = raw_index.get("index", {})
            except Exception:
                self.track_index = {}
        if self._playlist_file().exists():
            try:
                data = json.loads(self._playlist_file().read_text(encoding="utf-8"))
                self.mixes = data.get("library", [])
            except Exception:
                self.mixes = []

        self.featured_mixes = []
        if self.featured_file.exists():
            try:
                data = json.loads(self.featured_file.read_text(encoding="utf-8"))
                self.featured_mixes = data.get("featured", [])
            except Exception:
                self.featured_mixes = []

    def _save_library(self):
        payload = {"library": self.mixes}
        self._playlist_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.library_changed.emit()

    def _save_track_index(self):
        payload = {"index": self.track_index}
        self.index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_session(self):
        if not self.session_file.exists():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            source = data.get("source_mode", "library")
            self.source_combo.setCurrentIndex(0 if source == "library" else 1)
            self._source_mode = source
            self._favorites_only = bool(data.get("favorites_only", False))
            self.fav_only.setChecked(self._favorites_only)
            self._refresh_mix_list()
            self._set_volume(int(data.get("volume", 82)))
            self.crossfade_check.setChecked(bool(data.get("crossfade_enabled", True)))
            self.crossfade_seconds.setValue(max(1, min(5, int(data.get("crossfade_seconds", 2)))))
            idx = int(data.get("current_index", -1))
            if 0 <= idx < len(self.visible_mixes):
                self.mix_list.setCurrentRow(idx)
                self.load_mix(idx, autoplay=False, from_visible=True)
                pos = int(data.get("position_ms", 0))
                if self.player is not None:
                    self.player.setPosition(max(0, pos))
        except Exception:
            pass

    def save_session(self):
        payload = {
            "source_mode": self._source_mode,
            "favorites_only": self._favorites_only,
            "current_index": self.mix_list.currentRow(),
            "position_ms": int(self.player.position()) if self.player is not None else 0,
            "volume": int(self.volume.value()),
            "crossfade_enabled": bool(self.crossfade_check.isChecked()),
            "crossfade_seconds": int(self.crossfade_seconds.value()),
        }
        self.session_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _append_history(self, mix: dict):
        entry = {
            "title": mix.get("title", "Untitled"),
            "audio": mix.get("audio", ""),
            "ts": int(time.time()),
        }
        history = []
        if self.history_file.exists():
            try:
                history = json.loads(self.history_file.read_text(encoding="utf-8")).get("history", [])
            except Exception:
                history = []
        history.insert(0, entry)
        history = history[:200]
        self.history_file.write_text(json.dumps({"history": history}, indent=2), encoding="utf-8")

    def _current_catalog(self) -> list:
        return self.mixes if self._source_mode == "library" else self.featured_mixes

    def _refresh_mix_list(self):
        self.mix_list.clear()
        source = self._current_catalog()
        self.visible_mixes = []
        for idx, mix in enumerate(source):
            if self._favorites_only and not bool(mix.get("favorite", False)):
                continue
            self.visible_mixes.append(idx)
            star = "★ " if mix.get("favorite", False) else ""
            self.mix_list.addItem(QListWidgetItem(f"{star}{mix.get('title', 'Untitled')}"))

        self.count_label.setText(f"{len(self.visible_mixes)} tracks")
        if not self.visible_mixes:
            self.now_title.setText("No track loaded")
            self.status.setText("Add tracks or switch source.")

    def _on_source_changed(self):
        self._source_mode = self.source_combo.currentData()
        self._current_index = -1
        self._refresh_mix_list()

    def _on_favorites_filter(self):
        self._favorites_only = self.fav_only.isChecked()
        self._refresh_mix_list()

    def _select_item(self, item: QListWidgetItem):
        idx = self.mix_list.row(item)
        self.load_mix(idx, autoplay=True, from_visible=True)

    def _start_library_import(self, paths: list[str], context: str):
        if self._import_thread is not None:
            self.status.setText("Import already in progress.")
            return

        candidates = []
        for raw in paths:
            path = Path(raw).expanduser()
            if path.suffix.lower() in SUPPORTED_AUDIO_EXTS:
                candidates.append(str(path))
        if not candidates:
            self.status.setText("No supported audio files found.")
            return

        known = {str(Path(m.get("audio", "")).expanduser().resolve()) for m in self.mixes}
        self._import_context = context
        self._import_progress = QProgressDialog("Preparing import...", "Cancel", 0, 100, self)
        self._import_progress.setWindowTitle("Importing Audio")
        self._import_progress.setWindowModality(Qt.ApplicationModal)
        self._import_progress.setMinimumDuration(0)
        self._import_progress.setValue(0)
        self._import_progress.show()

        self.add_tracks_btn.setEnabled(False)
        self.scan_folder_btn.setEnabled(False)
        self.status.setText(f"{context} in progress...")

        self._import_thread = QThread(self)
        self._import_worker = LibraryImportWorker(candidates, known, dict(self.track_index))
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.finished.connect(self._cleanup_import)
        self._import_worker.failed.connect(self._cleanup_import)
        self._import_progress.canceled.connect(self._cancel_import)
        self._import_thread.start()

    def _on_import_progress(self, value: int, message: str):
        if self._import_progress is None:
            return
        self._import_progress.setLabelText(message)
        self._import_progress.setValue(max(0, min(100, value)))

    def _on_import_finished(self, result: dict):
        entries = result.get("entries", [])
        self.track_index = result.get("index", self.track_index)
        self._save_track_index()

        if entries:
            self.mixes.extend(entries)
            self._save_library()
            if self._source_mode == "library":
                self._refresh_mix_list()

        skipped = int(result.get("skipped_duplicates", 0) or 0)
        if result.get("canceled", False):
            self.feature.setText(
                f"{self._import_context} canceled: imported {len(entries)} track(s), skipped {skipped} duplicate(s)."
            )
            return

        self.feature.setText(
            f"{self._import_context} complete: imported {len(entries)} track(s), skipped {skipped} duplicate(s)."
        )
        self.status.setText("Library updated.")

    def _on_import_failed(self, error_text: str):
        self.status.setText(f"Import error: {error_text}")

    def _cancel_import(self):
        if self._import_worker is not None:
            self._import_worker.cancel()

    def _cleanup_import(self, *_args):
        self.add_tracks_btn.setEnabled(True)
        self.scan_folder_btn.setEnabled(True)
        if self._import_thread is not None:
            self._import_thread.quit()
            self._import_thread.wait(1500)
            self._import_thread.deleteLater()
        if self._import_worker is not None:
            self._import_worker.deleteLater()
        if self._import_progress is not None:
            self._import_progress.deleteLater()
        self._import_thread = None
        self._import_worker = None
        self._import_progress = None

    def add_tracks(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Tracks", str(Path.home()), "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All Files (*)")
        if not paths:
            return
        self._start_library_import(paths, "Add Tracks")

    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose Music Folder", str(Path.home()))
        if not folder:
            return
        root = Path(folder)
        paths = [str(path) for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTS]
        self._start_library_import(paths, "Folder Scan")

    def toggle_favorite_selected(self):
        row = self.mix_list.currentRow()
        if row < 0 or row >= len(self.visible_mixes):
            return
        source = self._current_catalog()
        actual = self.visible_mixes[row]
        source[actual]["favorite"] = not bool(source[actual].get("favorite", False))
        if self._source_mode == "library":
            self._save_library()
        self._refresh_mix_list()
        self.mix_list.setCurrentRow(min(row, self.mix_list.count() - 1))

    def _set_disc_from_url(self, url: str):
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        safe_ext = ext if ext in {".png", ".jpg", ".jpeg", ".webp"} else ".img"
        cache_name = f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}{safe_ext}"
        cache_path = self.art_cache_dir / cache_name
        if cache_path.exists():
            self._set_disc_from_local(str(cache_path))
            return
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = resp.read()
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                try:
                    cache_path.write_bytes(data)
                except Exception:
                    pass
                self._current_art = pix
                self.disc_label.setPixmap(pix.scaled(260, 260, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        except Exception:
            pass

    def _set_disc_from_local(self, path: str):
        pix = QPixmap(str(path))
        if not pix.isNull():
            self._current_art = pix
            self.disc_label.setPixmap(pix.scaled(260, 260, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def load_mix(self, index: int, autoplay: bool, from_visible: bool = True):
        if self.player is None:
            return
        if self._crossfade_in_progress:
            self._abort_crossfade()
        if from_visible:
            if index < 0 or index >= len(self.visible_mixes):
                return
            actual = self.visible_mixes[index]
        else:
            actual = index

        source = self._current_catalog()
        if actual < 0 or actual >= len(source):
            return
        mix = source[actual]
        self._append_history(mix)

        self._current_index = actual
        self.mix_changed.emit(actual)
        self.now_title.setText(mix.get("title", "Untitled"))
        self.status.setText(f"Loaded: {mix.get('title', 'Untitled')}")

        art = mix.get("art", "")
        if art:
            if str(art).startswith(("http://", "https://")):
                self._set_disc_from_url(art)
            else:
                self._set_disc_from_local(art)

        audio_src = mix.get("audio", "")
        media_url = QUrl(str(audio_src)) if str(audio_src).startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(audio_src).expanduser()))
        self.player.setMedia(QMediaContent(media_url))
        self.player.setPosition(0)
        self.player.setVolume(int(self.volume.value()))
        self._prime_next_track()
        if autoplay:
            self.player.play()

    def _prime_next_track(self):
        if self.player is None or self._alt_player is None:
            self._preloaded_actual_index = -1
            return
        if self.mix_list.count() <= 1:
            self._preloaded_actual_index = -1
            return
        row = self.mix_list.currentRow()
        if row < 0:
            self._preloaded_actual_index = -1
            return
        next_row = (row + 1) % self.mix_list.count()
        if next_row < 0 or next_row >= len(self.visible_mixes):
            self._preloaded_actual_index = -1
            return
        next_actual = self.visible_mixes[next_row]
        source = self._current_catalog()
        if next_actual < 0 or next_actual >= len(source):
            self._preloaded_actual_index = -1
            return
        mix = source[next_actual]
        audio_src = mix.get("audio", "")
        media_url = QUrl(str(audio_src)) if str(audio_src).startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(audio_src).expanduser()))
        try:
            self._alt_player.setMedia(QMediaContent(media_url))
            self._alt_player.setPosition(0)
            self._alt_player.setVolume(int(self.volume.value()))
            self._preloaded_actual_index = next_actual
        except Exception:
            self._preloaded_actual_index = -1

    def _abort_crossfade(self):
        self._crossfade_timer.stop()
        self._crossfade_in_progress = False
        self._crossfade_elapsed_ms = 0
        self._crossfade_duration_ms = 0
        self._crossfade_to_actual_index = -1
        if self.player is not None:
            self.player.setVolume(int(self.volume.value()))
        if self._alt_player is not None:
            if self._alt_player.state() == QMediaPlayer.PlayingState:
                self._alt_player.pause()
            self._alt_player.setPosition(0)
        self._preloaded_actual_index = -1

    def _set_volume(self, v: int):
        if self.player is not None:
            self.player.setVolume(int(v))
        if self._alt_player is not None and not self._crossfade_in_progress:
            self._alt_player.setVolume(int(v))
        self._crossfade_target_volume = int(v)

    def toggle_play(self):
        if self.player is None:
            return
        if self.mix_list.count() == 0:
            self.status.setText("No tracks loaded. Use Add Tracks or Scan Folder.")
            return
        if self._current_index < 0:
            self.mix_list.setCurrentRow(0)
            self.load_mix(0, autoplay=True, from_visible=True)
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_next(self):
        if self.mix_list.count() == 0:
            return
        row = self.mix_list.currentRow()
        row = 0 if row < 0 else (row + 1) % self.mix_list.count()
        self.mix_list.setCurrentRow(row)
        self.load_mix(row, autoplay=True, from_visible=True)

    def play_previous(self):
        if self.mix_list.count() == 0:
            return
        row = self.mix_list.currentRow()
        row = self.mix_list.count() - 1 if row <= 0 else row - 1
        self.mix_list.setCurrentRow(row)
        self.load_mix(row, autoplay=True, from_visible=True)

    def share_current_track_info(self):
        source = self._current_catalog()
        if self._current_index < 0 or self._current_index >= len(source):
            self.status.setText("No track selected to share.")
            return
        mix = source[self._current_index]
        title = str(mix.get("title", "Untitled")).strip() or "Untitled"
        audio = str(mix.get("audio", "")).strip()
        share_text = f"{title}\n{audio}" if audio else title
        try:
            QApplication.clipboard().setText(share_text)
            self.status.setText("Track info copied to clipboard.")
        except Exception:
            self.status.setText("Unable to copy track info.")

    def _fmt(self, ms: int) -> str:
        sec = max(0, int(ms / 1000))
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def _on_position(self, pos: int):
        self.time_label.setText(f"{self._fmt(pos)} / {self._fmt(getattr(self, '_duration_ms', 0))}")
        self._maybe_start_crossfade(pos)

    def _on_duration(self, dur: int):
        self._duration_ms = max(0, dur)
        self.time_label.setText(f"{self._fmt(self.player.position())} / {self._fmt(self._duration_ms)}")

    def _on_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.playback_state_changed.emit(True)
            self.play_btn.setText("Pause")
            self.status.setText(f"Playing: {self.now_title.text()}")
            self._disc_timer.start()
        else:
            self.playback_state_changed.emit(False)
            self.play_btn.setText("Play")
            if self._current_index >= 0:
                self.status.setText(f"Paused: {self.now_title.text()}")
            self._disc_timer.stop()

    def _on_media_status(self, status):
        if self.player is None:
            return
        if self._crossfade_in_progress:
            return
        if status == QMediaPlayer.EndOfMedia and self.mix_list.count() > 1:
            if not self.crossfade_check.isChecked() and self._alt_player is not None and self._preloaded_actual_index >= 0:
                self._disconnect_player_signals(self.player)
                current = self.player
                self.player = self._alt_player
                self._alt_player = current
                self._bind_player()
                self.player.setVolume(int(self.volume.value()))
                self.player.setPosition(0)
                self.player.play()
                self._current_index = self._preloaded_actual_index
                row = -1
                try:
                    row = self.visible_mixes.index(self._current_index)
                except Exception:
                    row = -1
                if row >= 0:
                    self.mix_list.blockSignals(True)
                    self.mix_list.setCurrentRow(row)
                    self.mix_list.blockSignals(False)
                source = self._current_catalog()
                if 0 <= self._current_index < len(source):
                    mix = source[self._current_index]
                    self.now_title.setText(mix.get("title", "Untitled"))
                    self.status.setText(f"Playing: {mix.get('title', 'Untitled')}")
                    self.mix_changed.emit(self._current_index)
                    self._append_history(mix)
                self._prime_next_track()
                return
        if status == QMediaPlayer.EndOfMedia and self.mix_list.count() > 1:
            self.play_next()

    def _maybe_start_crossfade(self, pos_ms: int):
        if self.player is None or self._alt_player is None:
            return
        if not self.crossfade_check.isChecked():
            return
        if self._crossfade_in_progress:
            return
        if self.mix_list.count() <= 1:
            return
        duration_ms = int(self.crossfade_seconds.value()) * 1000
        if duration_ms <= 0:
            return
        total = int(getattr(self, "_duration_ms", 0) or 0)
        if total <= 0:
            return
        remaining = total - int(pos_ms)
        if remaining > duration_ms:
            return

        row = self.mix_list.currentRow()
        if row < 0:
            return
        next_row = (row + 1) % self.mix_list.count()
        if next_row == row:
            return
        next_actual = self.visible_mixes[next_row]
        source = self._current_catalog()
        if next_actual < 0 or next_actual >= len(source):
            return
        mix = source[next_actual]
        audio_src = mix.get("audio", "")
        media_url = QUrl(str(audio_src)) if str(audio_src).startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(audio_src).expanduser()))

        self._crossfade_in_progress = True
        self._crossfade_elapsed_ms = 0
        self._crossfade_duration_ms = max(300, duration_ms)
        self._crossfade_to_actual_index = next_actual
        self._alt_player.setMedia(QMediaContent(media_url))
        self._alt_player.setVolume(0)
        self._alt_player.setPosition(0)
        self._alt_player.play()
        self._crossfade_timer.start()
        self.status.setText("Crossfading...")

    def _tick_crossfade(self):
        if not self._crossfade_in_progress or self.player is None or self._alt_player is None:
            self._crossfade_timer.stop()
            return
        self._crossfade_elapsed_ms += int(self._crossfade_timer.interval())
        ratio = min(1.0, self._crossfade_elapsed_ms / max(1, self._crossfade_duration_ms))
        target = int(self.volume.value())
        out_vol = int(target * (1.0 - ratio))
        in_vol = int(target * ratio)
        self.player.setVolume(max(0, min(100, out_vol)))
        self._alt_player.setVolume(max(0, min(100, in_vol)))

        if ratio < 1.0:
            return

        self._crossfade_timer.stop()
        old_player = self.player
        new_player = self._alt_player
        self._disconnect_player_signals(old_player)
        self.player = new_player
        self._alt_player = old_player
        self._bind_player()
        self.player.setVolume(target)
        self._duration_ms = int(self.player.duration())
        if self._alt_player is not None:
            self._alt_player.pause()
            self._alt_player.setPosition(0)
            self._alt_player.setVolume(target)

        self._current_index = self._crossfade_to_actual_index
        row = -1
        try:
            row = self.visible_mixes.index(self._current_index)
        except Exception:
            row = -1
        if row >= 0:
            self.mix_list.blockSignals(True)
            self.mix_list.setCurrentRow(row)
            self.mix_list.blockSignals(False)

        source = self._current_catalog()
        if 0 <= self._current_index < len(source):
            mix = source[self._current_index]
            self.now_title.setText(mix.get("title", "Untitled"))
            self.status.setText(f"Playing: {mix.get('title', 'Untitled')}")
            self.mix_changed.emit(self._current_index)
            self._append_history(mix)
            art = mix.get("art", "")
            if art:
                if str(art).startswith(("http://", "https://")):
                    self._set_disc_from_url(art)
                else:
                    self._set_disc_from_local(art)

        self._crossfade_in_progress = False
        self._crossfade_to_actual_index = -1
        self._crossfade_elapsed_ms = 0
        self._crossfade_duration_ms = 0
        self._prime_next_track()

    def _spin_disc(self):
        if self._current_art.isNull():
            return
        self._disc_angle = (self._disc_angle + 2) % 360
        src = self._current_art.scaled(260, 260, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        out = QPixmap(src.size())
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.translate(src.width() / 2, src.height() / 2)
        painter.rotate(self._disc_angle)
        painter.translate(-src.width() / 2, -src.height() / 2)
        painter.drawPixmap(0, 0, src)
        painter.end()
        self.disc_label.setPixmap(out)

    def stop(self):
        self._abort_crossfade()
        if self.player is not None and self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        if self._alt_player is not None and self._alt_player.state() == QMediaPlayer.PlayingState:
            self._alt_player.pause()
        if self._import_worker is not None:
            self._import_worker.cancel()
        if self._import_thread is not None:
            self._import_thread.quit()
            self._import_thread.wait(1500)
        self.save_session()


class KIMIXNowPlaying(QWidget):
    def __init__(self, playlist_view: KIMIXPlayer):
        super().__init__()
        self.playlist_view = playlist_view
        self._duration_ms = 0
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setSingleShot(True)
        self._sleep_timer.timeout.connect(self._sleep_timeout)
        self._setup_ui()
        self._apply_style()
        self._bind()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.stage = QFrame()
        self.stage.setObjectName("npStage")
        stage_layout = QVBoxLayout(self.stage)
        stage_layout.setContentsMargins(28, 20, 28, 24)
        root.addWidget(self.stage, 1)

        top = QHBoxLayout()
        logo = QLabel("KIMIX")
        logo.setObjectName("npLogo")
        top.addWidget(logo)
        top.addStretch(1)
        self.nav = QLabel("Browse  ·  Favorites")
        self.nav.setObjectName("npNav")
        top.addWidget(self.nav)
        stage_layout.addLayout(top)

        self.feature_label = QLabel("Now Playing")
        self.feature_label.setObjectName("npFeature")
        self.feature_label.setAlignment(Qt.AlignHCenter)
        stage_layout.addWidget(self.feature_label)

        self.title_label = QLabel("No track loaded")
        self.title_label.setObjectName("npTitle")
        self.title_label.setAlignment(Qt.AlignHCenter)
        stage_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Open Playlist mode to add tracks")
        self.subtitle_label.setObjectName("npSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignHCenter)
        stage_layout.addWidget(self.subtitle_label)

        self.eq_label = QLabel()
        self.eq_label.setObjectName("npEq")
        self.eq_label.setFixedHeight(110)
        stage_layout.addWidget(self.eq_label)

        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.sliderMoved.connect(self._seek_to)
        stage_layout.addWidget(self.progress)

        row = QHBoxLayout()
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("npTime")
        self.now_status = QLabel("Relax and enjoy the music")
        self.now_status.setObjectName("npStatus")
        row.addWidget(self.time_label)
        row.addStretch(1)
        row.addWidget(self.now_status)
        stage_layout.addLayout(row)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.prev_btn = QPushButton("⏮")
        self.play_btn = QPushButton("⏯")
        self.next_btn = QPushButton("⏭")
        self.prev_btn.clicked.connect(self.playlist_view.play_previous)
        self.play_btn.clicked.connect(self.playlist_view.toggle_play)
        self.next_btn.clicked.connect(self.playlist_view.play_next)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addSpacing(18)
        controls.addWidget(QLabel("Sleep"))
        self.sleep_minutes = QSpinBox()
        self.sleep_minutes.setRange(0, 240)
        self.sleep_minutes.setSuffix(" min")
        controls.addWidget(self.sleep_minutes)
        self.sleep_btn = QPushButton("Set")
        self.sleep_btn.clicked.connect(self._set_sleep_timer)
        controls.addWidget(self.sleep_btn)
        controls.addSpacing(18)
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(82)
        self.vol_slider.valueChanged.connect(self.playlist_view._set_volume)
        self.vol_slider.setFixedWidth(180)
        controls.addWidget(self.vol_slider)
        controls.addStretch(1)
        stage_layout.addLayout(controls)

    def _apply_style(self):
        self.setStyleSheet(
            """
            QWidget { color:#e9ecff; }
            QFrame#npStage { background:qradialgradient(cx:0.65, cy:0.30, radius:1.05, fx:0.65, fy:0.30, stop:0 rgba(255,167,123,0.26), stop:0.38 rgba(143,98,193,0.24), stop:0.72 rgba(62,46,112,0.42), stop:1 rgba(4,10,26,0.98)); }
            QLabel#npLogo { font-size: 52px; font-weight: 820; letter-spacing:3px; }
            QLabel#npNav { color: rgba(233,236,255,0.86); font-size: 18px; }
            QLabel#npFeature { color: rgba(233,236,255,0.86); font-size: 24px; }
            QLabel#npTitle { font-size: 70px; font-weight: 820; }
            QLabel#npSubtitle { font-size: 32px; color: rgba(233,236,255,0.82); }
            QLabel#npEq { background: rgba(255,255,255,0.03); border: 1px solid rgba(233,236,255,0.16); border-radius: 8px; }
            QLabel#npTime, QLabel#npStatus { font-size: 22px; color: rgba(233,236,255,0.90); }
            QPushButton { border: 1px solid rgba(233,236,255,0.20); border-radius: 16px; padding: 6px 12px; background: rgba(8,18,44,0.60); color: #f5f7ff; font-size: 20px; font-weight: 700; }
            """
        )

    def _bind(self):
        if self.playlist_view.player is None:
            self.now_status.setText("Playback backend unavailable.")
            return
        self.playlist_view.mix_changed.connect(self._set_mix_visual)
        self.playlist_view.playback_state_changed.connect(self._on_play_state)
        self.playlist_view.player.positionChanged.connect(self._on_position)
        self.playlist_view.player.durationChanged.connect(self._on_duration)
        self.playlist_view.library_changed.connect(self._on_library_changed)

    def _on_library_changed(self):
        if not self.playlist_view.mixes:
            self.title_label.setText("No track loaded")
            self.subtitle_label.setText("Open Playlist mode to add tracks")

    def _set_mix_visual(self, index: int):
        source = self.playlist_view._current_catalog()
        if index < 0 or index >= len(source):
            return
        mix = source[index]
        self.title_label.setText(mix.get("title", "Untitled"))
        src = str(mix.get("audio", ""))
        self.subtitle_label.setText(f"{Path(src).suffix.lstrip('.').upper() or 'Track'}")

    def _set_sleep_timer(self):
        minutes = self.sleep_minutes.value()
        if minutes <= 0:
            self._sleep_timer.stop()
            self.now_status.setText("Sleep timer off")
            return
        self._sleep_timer.start(minutes * 60 * 1000)
        self.now_status.setText(f"Sleep timer set: {minutes} min")

    def _sleep_timeout(self):
        self.playlist_view.stop()
        self.now_status.setText("Sleep timer reached. Playback stopped.")

    def _fmt(self, ms: int) -> str:
        sec = max(0, int(ms / 1000))
        return f"{sec // 60:02d}:{sec % 60:02d}"

    def _seek_to(self, value: int):
        if self.playlist_view.player is not None:
            self.playlist_view.player.setPosition(value)

    def _on_play_state(self, playing: bool):
        self.now_status.setText("Now Playing" if playing else "Paused")

    def _on_position(self, pos: int):
        self.progress.blockSignals(True)
        self.progress.setValue(pos)
        self.progress.blockSignals(False)
        self.time_label.setText(f"{self._fmt(pos)} / {self._fmt(self._duration_ms)}")
        self._render_eq(pos)

    def _on_duration(self, duration: int):
        self._duration_ms = max(0, duration)
        self.progress.setRange(0, self._duration_ms)

    def _render_eq(self, pos_ms: int):
        width = max(1, self.eq_label.width())
        height = max(1, self.eq_label.height())
        pix = QPixmap(width, height)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)

        waveform = []
        source = self.playlist_view._current_catalog()
        idx = self.playlist_view._current_index
        if 0 <= idx < len(source):
            waveform = source[idx].get("waveform", [])

        bars = 90
        mid = height // 2
        for i in range(bars):
            if waveform:
                wi = int((i / max(1, bars - 1)) * (len(waveform) - 1))
                amp = max(0.08, waveform[wi])
            else:
                phase = (i * 0.37) + (pos_ms / 1400.0)
                amp = (abs((phase % 2.0) - 1.0) * 0.75) + 0.10
            h = int((height - 10) * amp)
            x = int((i / bars) * width)
            c = QColor("#ff9a57") if i < bars // 3 else QColor("#b06dff")
            p.setPen(QPen(c, 3))
            p.drawLine(x, mid - h // 2, x, mid + h // 2)
        p.end()
        self.eq_label.setPixmap(pix)
