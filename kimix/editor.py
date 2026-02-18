import copy
import itertools
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

try:
    import numpy as np
    import sounddevice as sd
    SD_IMPORT_ERROR = ""
except Exception as exc:
    np = None
    sd = None
    SD_IMPORT_ERROR = str(exc)

from PyQt5.QtCore import Qt, QThread, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from .audio_engine import (
    AudioSegment,
    ExportWorker,
    PYDUB_IMPORT_ERROR,
    _play_with_simpleaudio,
    atempo_chain as _atempo_chain,
    high_pass_filter,
    low_pass_filter,
    resolve_clip_audio,
)
from .editor_core import AudioClip, Project, Track, ms_to_seconds_text, parse_time_to_ms
from .editor_recording import chunks_to_audiosegment, list_input_devices, peak_level
from .editor_storage import clip_metadata_dict, load_clip_audio_from_sources
from .editor_ui import ICONS, make_icon, style_icon_button
from .timeline import TimelineWidget



class AudioEditor(QMainWindow):
    SPEED_VALUES = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    FINAL_TRACK_NAME = "Final Product"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("KIMIX Editor")
        self.resize(1280, 650)

        self.projects: dict[str, Project] = {}
        self.current_project_name: Optional[str] = None

        self.clipboard_audio: Optional["AudioSegment"] = None
        self.clipboard_name = "Clip"
        self.clipboard_source_path = ""
        self.clipboard_source_in_ms = 0
        self.clipboard_source_out_ms = 0
        self.clipboard_reversed = False
        self.clipboard_volume_db = 0

        self.play_obj = None
        self.is_playing = False
        self.play_start_time = 0.0
        self.play_start_pos_ms = 0
        self.current_pos_ms = 0
        self._active_play_speed = 1.0
        self._active_base_mix_len = 0
        self._recording = False
        self._recording_stream = None
        self._recorded_chunks = []
        self._record_sample_rate = 44100
        self._record_channels = 1
        self._record_dtype = "float32"
        self._record_level = 0.0

        self._id_counter = itertools.count(1)
        self._mix_cache_key = None
        self._mix_cache = None
        self._source_segment_cache: dict[tuple[str, int, int, bool], "AudioSegment"] = {}
        self._state_dir = Path.home() / ".kimix"
        self._media_dir = self._state_dir / "media"
        self._projects_file = self._state_dir / "projects.json"
        self._undo_stacks: dict[str, list[Project]] = {}
        self._redo_stacks: dict[str, list[Project]] = {}
        self._history_limit = 25
        self._suspend_history = False

        self._build_ui()
        self._apply_theme()
        self._wire_icons()

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._update_playback_ui)
        self.record_level_timer = QTimer(self)
        self.record_level_timer.setInterval(60)
        self.record_level_timer.timeout.connect(self._update_record_level_meter)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._save_projects_to_disk)
        self._export_thread = None
        self._export_worker = None
        self._export_progress = None
        self._is_closing = False

        if PYDUB_IMPORT_ERROR:
            self._set_controls_enabled(False)
            QMessageBox.critical(
                self,
                "Dependency Error",
                (
                    f"{PYDUB_IMPORT_ERROR}\n\n"
                    "Fix:\n"
                    "1) Use Python 3.11 or 3.12\n"
                    "2) Install: pip install PyQt5 pydub simpleaudio\n"
                    "3) Ensure ffmpeg is installed and on PATH"
                ),
            )
        elif SD_IMPORT_ERROR:
            self.record_btn.setEnabled(False)
            self.status_label.setText("Mic recording unavailable: install sounddevice + numpy.")

        self._load_projects_from_disk()

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QWidget {
                background-color: #0a1220;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
            }
            QLineEdit, QComboBox {
                background-color: #101b2e;
                color: #ffffff;
                border: 1px solid #d7ccb6;
                border-radius: 4px;
                padding: 4px 6px;
                font-weight: 700;
            }
            QPushButton {
                background-color: #0f1a2d;
                border-top: 1px solid #2a3954;
                border-left: 1px solid #2a3954;
                border-right: 2px solid #efe1c2;
                border-bottom: 2px solid #efe1c2;
                border-radius: 4px;
                padding: 5px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #17263d;
            }
            QPushButton:pressed {
                background-color: #223758;
            }
            QLabel {
                color: #f8f4e8;
            }
            QCheckBox {
                color: #ffffff;
                font-weight: 700;
            }
            QSlider::groove:horizontal {
                border: 1px solid #2a3954;
                height: 7px;
                background: #0d182a;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #d18d53;
                border: 1px solid #f4e7cb;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            """
        )

    def _wire_icons(self):
        for button in [
            self.add_audio_btn,
            self.cut_btn,
            self.copy_btn,
            self.paste_btn,
            self.delete_btn,
            self.split_btn,
            self.export_btn,
            self.stop_btn,
            self.play_pause_btn,
            self.record_btn,
            self.mute_track_btn,
        ]:
            style_icon_button(button)

        self.add_audio_btn.setIcon(make_icon(ICONS["add"]))
        self.cut_btn.setIcon(make_icon(ICONS["cut"]))
        self.copy_btn.setIcon(make_icon(ICONS["copy"]))
        self.paste_btn.setIcon(make_icon(ICONS["paste"]))
        self.delete_btn.setIcon(make_icon(ICONS["delete"]))
        self.split_btn.setIcon(make_icon(ICONS["splice"]))
        self.export_btn.setIcon(make_icon(ICONS["export"]))
        self.stop_btn.setIcon(make_icon(ICONS["stop"]))
        self.play_pause_btn.setIcon(make_icon(ICONS["play"]))
        self.record_btn.setIcon(make_icon(ICONS["record"]))
        self.mute_track_btn.setIcon(make_icon(ICONS["mute"]))

        self.add_audio_btn.setToolTip("Add Audio")
        self.cut_btn.setToolTip("Cut")
        self.copy_btn.setToolTip("Copy")
        self.paste_btn.setToolTip("Paste")
        self.delete_btn.setToolTip("Delete")
        self.split_btn.setToolTip("Split at Playhead")
        self.export_btn.setToolTip("Export")
        self.stop_btn.setToolTip("Stop")
        self.play_pause_btn.setToolTip("Play/Pause")
        self.record_btn.setToolTip("Start/Stop Recording")
        self.mute_track_btn.setToolTip("Mute/Unmute Selected Row")

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)

        top = QHBoxLayout()
        main.addLayout(top)

        self.new_project_btn = QPushButton("New Project")
        self.new_project_btn.clicked.connect(self.new_project)
        top.addWidget(self.new_project_btn)

        self.open_project_btn = QPushButton("Open Project")
        self.open_project_btn.clicked.connect(self.open_project_file)
        top.addWidget(self.open_project_btn)

        self.save_project_as_btn = QPushButton("Save Project As")
        self.save_project_as_btn.clicked.connect(self.save_project_as_file)
        top.addWidget(self.save_project_as_btn)

        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.undo_last)
        top.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("Redo")
        self.redo_btn.clicked.connect(self.redo_last)
        top.addWidget(self.redo_btn)

        self.project_combo = QComboBox()
        self.project_combo.currentTextChanged.connect(self.switch_project)
        self.project_combo.setMinimumWidth(220)
        top.addWidget(self.project_combo)

        self.add_audio_btn = QPushButton("")
        self.add_audio_btn.clicked.connect(self.add_audio_files)
        top.addWidget(self.add_audio_btn)

        self.record_btn = QPushButton("")
        self.record_btn.clicked.connect(self.toggle_recording)
        top.addWidget(self.record_btn)

        self.play_pause_btn = QPushButton("")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)
        top.addWidget(self.play_pause_btn)

        self.stop_btn = QPushButton("")
        self.stop_btn.clicked.connect(self.stop_and_rewind)
        top.addWidget(self.stop_btn)

        self.export_btn = QPushButton("")
        self.export_btn.clicked.connect(self.export_mix)
        top.addWidget(self.export_btn)

        self.mute_track_btn = QPushButton("")
        self.mute_track_btn.clicked.connect(self.toggle_selected_track_mute)
        top.addWidget(self.mute_track_btn)

        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(0)
        self.seek_slider.sliderMoved.connect(self.seek_to)
        main.addWidget(self.seek_slider)

        controls = QGridLayout()
        main.addLayout(controls)

        self.duration_label = QLabel("Duration: 0.00 s")
        self.position_label = QLabel("Position: 0.00 s")
        controls.addWidget(self.duration_label, 0, 0)
        controls.addWidget(self.position_label, 0, 1)

        controls.addWidget(QLabel("Start (s or mm:ss):"), 1, 0)
        self.start_input = QLineEdit("0.0")
        controls.addWidget(self.start_input, 1, 1)

        controls.addWidget(QLabel("End (s or mm:ss):"), 1, 2)
        self.end_input = QLineEdit("0.0")
        controls.addWidget(self.end_input, 1, 3)

        controls.addWidget(QLabel("Speed:"), 2, 0)
        self.speed_combo = QComboBox()
        for value in self.SPEED_VALUES:
            self.speed_combo.addItem(f"{value}x", value)
        self.speed_combo.setCurrentText("1.0x")
        controls.addWidget(self.speed_combo, 2, 1)

        self.pitch_change_checkbox = QCheckBox("Pitch Changes With Speed")
        self.pitch_change_checkbox.setChecked(False)
        controls.addWidget(self.pitch_change_checkbox, 2, 2)

        self.fade_checkbox = QCheckBox("Fade Spliced Clips")
        self.fade_checkbox.setChecked(True)
        self.fade_checkbox.stateChanged.connect(self._clear_mix_cache)
        self.fade_checkbox.stateChanged.connect(self._on_playback_setting_changed)
        controls.addWidget(self.fade_checkbox, 2, 3)

        controls.addWidget(QLabel("Fade ms:"), 3, 0)
        self.fade_input = QLineEdit("40")
        self.fade_input.textChanged.connect(self._clear_mix_cache)
        self.fade_input.textChanged.connect(self._on_playback_setting_changed)
        controls.addWidget(self.fade_input, 3, 1)

        controls.addWidget(QLabel("Volume Boost (dB):"), 3, 2)
        self.volume_combo = QComboBox()
        for db in [0, 3, 6, 9, 12, 15, 18]:
            self.volume_combo.addItem(f"+{db} dB", db)
        self.volume_combo.currentIndexChanged.connect(self._clear_mix_cache)
        self.volume_combo.currentIndexChanged.connect(self._on_playback_setting_changed)
        controls.addWidget(self.volume_combo, 3, 3)

        self.noise_reduction_checkbox = QCheckBox("Reduce Background Noise")
        self.noise_reduction_checkbox.setChecked(False)
        self.noise_reduction_checkbox.stateChanged.connect(self._clear_mix_cache)
        self.noise_reduction_checkbox.stateChanged.connect(self._on_playback_setting_changed)
        controls.addWidget(self.noise_reduction_checkbox, 4, 0, 1, 2)

        self.speed_combo.currentIndexChanged.connect(self._on_playback_setting_changed)
        self.pitch_change_checkbox.stateChanged.connect(self._on_playback_setting_changed)

        self.reverse_btn = QPushButton("Reverse Selected Clip To New Row")
        self.reverse_btn.clicked.connect(self.reverse_selected_clip)
        controls.addWidget(self.reverse_btn, 4, 2, 1, 2)

        controls.addWidget(QLabel("Track Volume (dB):"), 5, 0)
        self.track_volume_slider = QSlider(Qt.Horizontal)
        self.track_volume_slider.setRange(-24, 12)
        self.track_volume_slider.setValue(0)
        self.track_volume_slider.valueChanged.connect(self._on_track_volume_changed)
        controls.addWidget(self.track_volume_slider, 5, 1, 1, 2)
        self.track_volume_value = QLabel("0 dB")
        controls.addWidget(self.track_volume_value, 5, 3)

        controls.addWidget(QLabel("Clip Volume (dB):"), 6, 0)
        self.clip_volume_slider = QSlider(Qt.Horizontal)
        self.clip_volume_slider.setRange(-24, 12)
        self.clip_volume_slider.setValue(0)
        self.clip_volume_slider.valueChanged.connect(self._on_clip_volume_changed)
        controls.addWidget(self.clip_volume_slider, 6, 1, 1, 2)
        self.clip_volume_value = QLabel("0 dB")
        controls.addWidget(self.clip_volume_value, 6, 3)

        controls.addWidget(QLabel("Input Device:"), 7, 0)
        self.input_device_combo = QComboBox()
        controls.addWidget(self.input_device_combo, 7, 1, 1, 2)
        self.monitor_checkbox = QCheckBox("Monitor Input While Recording")
        controls.addWidget(self.monitor_checkbox, 7, 3)

        controls.addWidget(QLabel("Input Level:"), 8, 0)
        self.record_level_bar = QProgressBar()
        self.record_level_bar.setRange(0, 100)
        self.record_level_bar.setValue(0)
        controls.addWidget(self.record_level_bar, 8, 1, 1, 3)

        controls.addWidget(QLabel("Timeline Zoom:"), 9, 0)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 320)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        controls.addWidget(self.zoom_slider, 9, 1, 1, 2)
        self.zoom_value = QLabel("100%")
        controls.addWidget(self.zoom_value, 9, 3)

        self.status_label = QLabel("Drag clips across rows into Final Product. Hold Ctrl while dragging to disable snap.")
        main.addWidget(self.status_label)

        ops = QHBoxLayout()
        main.addLayout(ops)

        self.cut_btn = QPushButton("")
        self.cut_btn.clicked.connect(self.cut_selection)
        ops.addWidget(self.cut_btn)

        self.copy_btn = QPushButton("")
        self.copy_btn.clicked.connect(self.copy_selection)
        ops.addWidget(self.copy_btn)

        self.paste_btn = QPushButton("")
        self.paste_btn.clicked.connect(self.paste_clipboard)
        ops.addWidget(self.paste_btn)

        self.delete_btn = QPushButton("")
        self.delete_btn.clicked.connect(self.delete_selection)
        ops.addWidget(self.delete_btn)

        self.split_btn = QPushButton("")
        self.split_btn.clicked.connect(self.split_selected_clip)
        ops.addWidget(self.split_btn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        main.addWidget(self.scroll, 1)

        self.timeline = TimelineWidget()
        self.timeline.selection_changed.connect(self._on_timeline_selection)
        self.timeline.playhead_changed.connect(self._on_timeline_playhead)
        self.timeline.clips_changed.connect(self._on_project_edited)
        self.timeline.track_rename_requested.connect(self.rename_track)
        self.timeline.edit_started.connect(self._push_undo_state)
        self.scroll.setWidget(self.timeline)
        self.timeline.set_zoom_px_per_sec(self.zoom_slider.value())
        self._populate_input_devices()

    def _set_controls_enabled(self, enabled: bool):
        widgets = [
            self.new_project_btn,
            self.open_project_btn,
            self.save_project_as_btn,
            self.undo_btn,
            self.redo_btn,
            self.project_combo,
            self.add_audio_btn,
            self.record_btn,
            self.play_pause_btn,
            self.stop_btn,
            self.export_btn,
            self.mute_track_btn,
            self.seek_slider,
            self.start_input,
            self.end_input,
            self.speed_combo,
            self.pitch_change_checkbox,
            self.fade_checkbox,
            self.fade_input,
            self.volume_combo,
            self.noise_reduction_checkbox,
            self.reverse_btn,
            self.track_volume_slider,
            self.clip_volume_slider,
            self.input_device_combo,
            self.monitor_checkbox,
            self.record_level_bar,
            self.zoom_slider,
            self.cut_btn,
            self.copy_btn,
            self.paste_btn,
            self.delete_btn,
            self.split_btn,
            self.timeline,
        ]
        for item in widgets:
            item.setEnabled(enabled)

    def _populate_input_devices(self):
        self.input_device_combo.clear()
        self.input_device_combo.addItem("Default Input", None)
        if SD_IMPORT_ERROR:
            self.input_device_combo.setEnabled(False)
            self.monitor_checkbox.setEnabled(False)
            return
        devices = list_input_devices(sd)
        if not devices:
            self.input_device_combo.setEnabled(False)
            self.monitor_checkbox.setEnabled(False)
            return
        for index, label in devices:
            self.input_device_combo.addItem(label, index)

    def _selected_input_device(self):
        data = self.input_device_combo.currentData()
        return data if data is not None else None

    def _refresh_selected_track_volume(self):
        project = self.current_project
        t_idx = self.timeline.selected_track
        if not project or t_idx < 0 or t_idx >= len(project.tracks):
            self.track_volume_slider.blockSignals(True)
            self.track_volume_slider.setValue(0)
            self.track_volume_slider.blockSignals(False)
            self.track_volume_value.setText("0 dB")
            return
        value = int(getattr(project.tracks[t_idx], "volume_db", 0) or 0)
        self.track_volume_slider.blockSignals(True)
        self.track_volume_slider.setValue(max(-24, min(12, value)))
        self.track_volume_slider.blockSignals(False)
        self.track_volume_value.setText(f"{value:+d} dB")

    def _refresh_selected_clip_volume(self):
        _track, clip, _t_idx, _c_idx = self._selected_clip_ref()
        if clip is None:
            self.clip_volume_slider.blockSignals(True)
            self.clip_volume_slider.setValue(0)
            self.clip_volume_slider.blockSignals(False)
            self.clip_volume_value.setText("0 dB")
            return
        value = int(getattr(clip, "volume_db", 0) or 0)
        self.clip_volume_slider.blockSignals(True)
        self.clip_volume_slider.setValue(max(-24, min(12, value)))
        self.clip_volume_slider.blockSignals(False)
        self.clip_volume_value.setText(f"{value:+d} dB")

    def _on_track_volume_changed(self, value: int):
        project = self.current_project
        t_idx = self.timeline.selected_track
        self.track_volume_value.setText(f"{int(value):+d} dB")
        if not project or t_idx < 0 or t_idx >= len(project.tracks):
            return
        self._push_undo_state()
        project.tracks[t_idx].volume_db = int(value)
        self._mark_project_dirty()
        self._refresh_timeline_ui()

    def _on_clip_volume_changed(self, value: int):
        self.clip_volume_value.setText(f"{int(value):+d} dB")
        track, clip, _t_idx, _c_idx = self._selected_clip_ref()
        if track is None or clip is None:
            return
        self._push_undo_state()
        clip.volume_db = int(value)
        self._mark_project_dirty()
        self._refresh_timeline_ui()

    def _current_speed(self) -> float:
        return float(self.speed_combo.currentData())

    def _current_volume_boost(self) -> int:
        return int(self.volume_combo.currentData())

    def _fade_ms(self) -> int:
        try:
            value = int(self.fade_input.text().strip())
        except ValueError:
            value = 0
        return max(0, value)

    def _clear_mix_cache(self, *_args):
        self._mix_cache_key = None
        self._mix_cache = None
        self._source_segment_cache.clear()

    def _on_playback_setting_changed(self, *_args):
        self._clear_mix_cache()
        if self.is_playing:
            self.stop_playback()
            self.start_playback()

    def _on_zoom_changed(self, value: int):
        self.zoom_value.setText(f"{int(value)}%")
        self.timeline.set_zoom_px_per_sec(int(value))

    @property
    def current_project(self) -> Optional[Project]:
        if not self.current_project_name:
            return None
        return self.projects.get(self.current_project_name)

    def _mark_project_dirty(self):
        project = self.current_project
        if project:
            project.revision += 1
        self._clear_mix_cache()
        self._schedule_autosave()

    def _ensure_final_product_track(self, project: Project):
        if project is None:
            return
        final_idx = -1
        for idx, track in enumerate(project.tracks):
            if getattr(track, "is_final_product", False) or track.name.strip().lower() == self.FINAL_TRACK_NAME.lower():
                final_idx = idx
                break
        if final_idx < 0:
            project.tracks.insert(0, Track(name=self.FINAL_TRACK_NAME, is_final_product=True))
        else:
            final_track = project.tracks.pop(final_idx)
            final_track.name = self.FINAL_TRACK_NAME
            final_track.is_final_product = True
            project.tracks.insert(0, final_track)
        for track in project.tracks[1:]:
            track.is_final_product = False

    def _prune_empty_tracks(self, project: Optional[Project]) -> bool:
        if project is None:
            return False
        before = len(project.tracks)
        kept_tracks = []
        for track in project.tracks:
            if getattr(track, "is_final_product", False):
                kept_tracks.append(track)
                continue
            if track.clips:
                kept_tracks.append(track)
        project.tracks = kept_tracks
        self._ensure_final_product_track(project)
        return len(project.tracks) != before

    def _ensure_track(self, project: Project, index: int) -> Track:
        while len(project.tracks) <= index:
            project.tracks.append(Track(name=self._next_standard_track_name(project)))
        return project.tracks[index]

    def _next_standard_track_name(self, project: Project, suffix: str = "") -> str:
        number = 1 + sum(1 for track in project.tracks if not getattr(track, "is_final_product", False))
        return f"Track {number}{suffix}"

    def _history_key(self) -> Optional[str]:
        return self.current_project_name

    def _clone_project(self, project: Project) -> Project:
        return copy.deepcopy(project)

    def _push_undo_state(self):
        if self._suspend_history:
            return
        key = self._history_key()
        project = self.current_project
        if not key or project is None:
            return
        stack = self._undo_stacks.setdefault(key, [])
        stack.append(self._clone_project(project))
        if len(stack) > self._history_limit:
            del stack[0]
        self._redo_stacks[key] = []

    def undo_last(self):
        key = self._history_key()
        project = self.current_project
        if not key or project is None:
            return
        stack = self._undo_stacks.get(key, [])
        if not stack:
            return
        prev = stack.pop()
        self._redo_stacks.setdefault(key, []).append(self._clone_project(project))
        self._suspend_history = True
        try:
            self.projects[key] = prev
            self._ensure_final_product_track(self.projects[key])
            self.timeline.set_project(self.projects[key])
            self._mark_project_dirty()
            self._refresh_timeline_ui()
        finally:
            self._suspend_history = False

    def redo_last(self):
        key = self._history_key()
        project = self.current_project
        if not key or project is None:
            return
        stack = self._redo_stacks.get(key, [])
        if not stack:
            return
        nxt = stack.pop()
        self._undo_stacks.setdefault(key, []).append(self._clone_project(project))
        self._suspend_history = True
        try:
            self.projects[key] = nxt
            self._ensure_final_product_track(self.projects[key])
            self.timeline.set_project(self.projects[key])
            self._mark_project_dirty()
            self._refresh_timeline_ui()
        finally:
            self._suspend_history = False

    def _reseed_clip_counter(self):
        max_id = 0
        for project in self.projects.values():
            for track in project.tracks:
                for clip in track.clips:
                    max_id = max(max_id, clip.clip_id)
        self._id_counter = itertools.count(max_id + 1 if max_id > 0 else 1)

    def _schedule_autosave(self):
        self._autosave_timer.start(350)

    def _compute_waveform_preview(self, audio: "AudioSegment", bins: int = 180) -> list[float]:
        samples = audio.get_array_of_samples()
        if not samples:
            return [0.0] * bins

        channels = max(1, audio.channels)
        total_frames = max(1, len(samples) // channels)
        max_amp = float(1 << (8 * audio.sample_width - 1))
        preview = []

        for bin_idx in range(bins):
            start_f = int((bin_idx * total_frames) / bins)
            end_f = int(((bin_idx + 1) * total_frames) / bins)
            if end_f <= start_f:
                end_f = min(total_frames, start_f + 1)

            peak = 0.0
            for frame in range(start_f, end_f):
                base = frame * channels
                acc = 0.0
                for ch in range(channels):
                    acc += abs(samples[base + ch])
                peak = max(peak, acc / channels)
            preview.append(min(1.0, peak / max_amp))

        return preview

    def _persist_clip_media(self, clip: AudioClip):
        self._media_dir.mkdir(parents=True, exist_ok=True)
        if not clip.media_filename:
            clip.media_filename = f"clip_{clip.clip_id}.wav"
        out_path = self._media_dir / clip.media_filename
        clip.audio.export(out_path, format="wav")

    def _build_clip(
        self,
        name: str,
        audio: "AudioSegment",
        start_ms: int,
        spliced: bool,
        source_path: str = "",
        source_in_ms: int = 0,
        source_out_ms: int = 0,
        reversed_audio: bool = False,
        volume_db: int = 0,
    ) -> AudioClip:
        clip = AudioClip(
            clip_id=next(self._id_counter),
            name=name,
            audio=audio,
            start_ms=start_ms,
            spliced=spliced,
            source_path=source_path,
            source_in_ms=max(0, int(source_in_ms)),
            source_out_ms=max(0, int(source_out_ms)) if source_out_ms else len(audio),
            reversed_audio=bool(reversed_audio),
            volume_db=int(volume_db),
        )
        clip.waveform_preview = self._compute_waveform_preview(audio)
        self._persist_clip_media(clip)
        return clip

    def _build_derived_clip(
        self,
        parent: AudioClip,
        name: str,
        audio: "AudioSegment",
        start_ms: int,
        spliced: bool,
        local_start_ms: int,
        local_end_ms: int,
    ) -> AudioClip:
        source_path = parent.source_path
        source_in_ms = 0
        source_out_ms = len(audio)
        if source_path:
            base_in = max(0, int(parent.source_in_ms))
            source_in_ms = base_in + max(0, int(local_start_ms))
            source_out_ms = base_in + max(0, int(local_end_ms))
        return self._build_clip(
            name=name,
            audio=audio,
            start_ms=start_ms,
            spliced=spliced,
            source_path=source_path,
            source_in_ms=source_in_ms,
            source_out_ms=source_out_ms,
            reversed_audio=parent.reversed_audio,
            volume_db=int(getattr(parent, "volume_db", 0) or 0),
        )

    def _save_projects_to_disk(self):
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._media_dir.mkdir(parents=True, exist_ok=True)

            payload = {
                "current_project_name": self.current_project_name,
                "projects": [],
            }

            for project_name, project in self.projects.items():
                proj_data = {"name": project_name, "tracks": []}

                non_empty_tracks = []
                final_track = None
                for track in project.tracks:
                    is_final = bool(getattr(track, "is_final_product", False)) or track.name.strip().lower() == self.FINAL_TRACK_NAME.lower()
                    if is_final and final_track is None:
                        final_track = track
                        continue
                    if track.clips:
                        non_empty_tracks.append(track)
                if final_track is None:
                    final_track = Track(name=self.FINAL_TRACK_NAME, is_final_product=True)
                serial_tracks = [final_track] + non_empty_tracks

                for track in serial_tracks:
                    is_final_serial = bool(getattr(track, "is_final_product", False)) or track is final_track
                    track_data = {
                        "name": self.FINAL_TRACK_NAME if is_final_serial else track.name,
                        "muted": track.muted,
                        "volume_db": int(getattr(track, "volume_db", 0) or 0),
                        "is_final_product": is_final_serial,
                        "clips": [],
                    }
                    for clip in track.clips:
                        self._persist_clip_media(clip)
                        track_data["clips"].append(clip_metadata_dict(clip, clip.media_filename))
                    proj_data["tracks"].append(track_data)
                payload["projects"].append(proj_data)

            self._projects_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            if not self._is_closing:
                try:
                    self.status_label.setText(f"Autosave warning: {exc}")
                except Exception:
                    pass

    def _load_projects_from_disk(self):
        if not self._projects_file.exists():
            return

        try:
            raw = json.loads(self._projects_file.read_text(encoding="utf-8"))
            loaded_projects: dict[str, Project] = {}
            max_clip_id = 0

            for proj_obj in raw.get("projects", []):
                project = Project(name=proj_obj["name"])
                for track_obj in proj_obj.get("tracks", []):
                    track = Track(
                        name=track_obj.get("name", "Track"),
                        muted=bool(track_obj.get("muted", False)),
                        volume_db=int(track_obj.get("volume_db", 0) or 0),
                        is_final_product=bool(track_obj.get("is_final_product", False)),
                    )
                    for clip_obj in track_obj.get("clips", []):
                        media_filename = clip_obj.get("media_filename", "")
                        media_path = self._media_dir / media_filename
                        loaded = load_clip_audio_from_sources(clip_obj, media_path if media_filename else Path(""))
                        audio = loaded["audio"]
                        if audio is None:
                            continue
                        clip_id = int(clip_obj.get("clip_id", 0))
                        max_clip_id = max(max_clip_id, clip_id)
                        clip = AudioClip(
                            clip_id=clip_id,
                            name=clip_obj.get("name", media_path.name),
                            audio=audio,
                            start_ms=int(clip_obj.get("start_ms", 0)),
                            spliced=bool(clip_obj.get("spliced", False)),
                            media_filename=media_filename,
                            waveform_preview=self._compute_waveform_preview(audio),
                            source_path=loaded["source_path"],
                            source_in_ms=loaded["source_in_ms"],
                            source_out_ms=loaded["source_out_ms"] if loaded["source_out_ms"] > 0 else len(audio),
                            reversed_audio=loaded["reversed_audio"],
                            volume_db=loaded["volume_db"],
                        )
                        track.clips.append(clip)
                    project.tracks.append(track)
                self._ensure_final_product_track(project)
                loaded_projects[project.name] = project

            self.projects = loaded_projects
            self._undo_stacks = {name: [] for name in self.projects}
            self._redo_stacks = {name: [] for name in self.projects}
            self.project_combo.blockSignals(True)
            self.project_combo.clear()
            for project_name in self.projects:
                self.project_combo.addItem(project_name)
            self.project_combo.blockSignals(False)

            self._reseed_clip_counter()

            preferred = raw.get("current_project_name")
            if preferred and preferred in self.projects:
                self.project_combo.setCurrentText(preferred)
                self.switch_project(preferred)
            elif self.projects:
                first = next(iter(self.projects.keys()))
                self.project_combo.setCurrentText(first)
                self.switch_project(first)
        except Exception as exc:
            self.status_label.setText(f"Load warning: {exc}")

    def _unique_project_name(self, base_name: str) -> str:
        if base_name not in self.projects:
            return base_name
        idx = 2
        while f"{base_name} ({idx})" in self.projects:
            idx += 1
        return f"{base_name} ({idx})"

    def save_project_as_file(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            str(Path.home() / f"{project.name}.kimix.json"),
            "KIMIX Project (*.kimix.json);;JSON (*.json)",
        )
        if not out_path:
            return

        try:
            project_file = Path(out_path)
            media_dir = project_file.parent / f"{project_file.stem}_media"
            media_dir.mkdir(parents=True, exist_ok=True)

            payload = {
                "format": "kimix-project-v1",
                "project": {
                    "name": project.name,
                    "tracks": [],
                },
                "media_folder": media_dir.name,
            }

            for track in project.tracks:
                track_data = {
                    "name": track.name,
                    "muted": track.muted,
                    "volume_db": int(getattr(track, "volume_db", 0) or 0),
                    "is_final_product": bool(getattr(track, "is_final_product", False)),
                    "clips": [],
                }
                for clip in track.clips:
                    media_name = f"clip_{clip.clip_id}.wav"
                    clip.audio.export(media_dir / media_name, format="wav")
                    track_data["clips"].append(clip_metadata_dict(clip, media_name))
                payload["project"]["tracks"].append(track_data)

            project_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.status_label.setText(f"Saved project file: {project_file}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Project Error", str(exc))

    def open_project_file(self):
        in_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project File",
            str(Path.home()),
            "KIMIX Project (*.kimix.json);;JSON (*.json)",
        )
        if not in_path:
            return

        try:
            project_file = Path(in_path)
            raw = json.loads(project_file.read_text(encoding="utf-8"))

            fmt = raw.get("format")
            if fmt not in ("kimix-project-v1", "twilight-project-v1") or "project" not in raw:
                raise ValueError("Unsupported project file format.")

            source_project = raw["project"]
            base_name = source_project.get("name", project_file.stem)
            project_name = self._unique_project_name(base_name)
            project = Project(name=project_name)

            media_folder = raw.get("media_folder", f"{project_file.stem}_media")
            media_dir = project_file.parent / media_folder

            for track_obj in source_project.get("tracks", []):
                track = Track(
                    name=track_obj.get("name", "Track"),
                    muted=bool(track_obj.get("muted", False)),
                    volume_db=int(track_obj.get("volume_db", 0) or 0),
                    is_final_product=bool(track_obj.get("is_final_product", False)),
                )
                for clip_obj in track_obj.get("clips", []):
                    media_filename = clip_obj.get("media_filename", "")
                    media_path = media_dir / media_filename
                    loaded = load_clip_audio_from_sources(clip_obj, media_path if media_filename else Path(""))
                    audio = loaded["audio"]
                    if audio is None:
                        continue
                    clip_id = int(clip_obj.get("clip_id", 0))
                    clip = AudioClip(
                        clip_id=clip_id if clip_id > 0 else next(self._id_counter),
                        name=clip_obj.get(
                            "name",
                            media_path.name if media_filename else Path(loaded["source_path"]).name,
                        ),
                        audio=audio,
                        start_ms=int(clip_obj.get("start_ms", 0)),
                        spliced=bool(clip_obj.get("spliced", False)),
                        media_filename=media_filename,
                        waveform_preview=self._compute_waveform_preview(audio),
                        source_path=loaded["source_path"],
                        source_in_ms=loaded["source_in_ms"],
                        source_out_ms=loaded["source_out_ms"] if loaded["source_out_ms"] > 0 else len(audio),
                        reversed_audio=loaded["reversed_audio"],
                        volume_db=loaded["volume_db"],
                    )
                    self._persist_clip_media(clip)
                    track.clips.append(clip)
                project.tracks.append(track)
            self._ensure_final_product_track(project)

            self.projects[project_name] = project
            self._undo_stacks[project_name] = []
            self._redo_stacks[project_name] = []
            self._reseed_clip_counter()
            self.project_combo.addItem(project_name)
            self.project_combo.setCurrentText(project_name)
            self._mark_project_dirty()
            self._refresh_timeline_ui()
            self.status_label.setText(f"Opened project: {project_name}")
        except Exception as exc:
            QMessageBox.critical(self, "Open Project Error", str(exc))

    def new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Project name cannot be empty.")
            return
        if name in self.projects:
            QMessageBox.warning(self, "Duplicate Name", "A project with that name already exists.")
            return

        project = Project(name=name)
        self._ensure_final_product_track(project)
        self.projects[name] = project
        self._undo_stacks[name] = []
        self._redo_stacks[name] = []
        self.project_combo.addItem(name)
        self.project_combo.setCurrentText(name)
        self._schedule_autosave()

    def switch_project(self, name: str):
        self.stop_playback()
        if self._recording:
            self.stop_recording()
        if not name:
            self.current_project_name = None
            self.timeline.set_project(None)
            self._refresh_timeline_ui()
            self._refresh_selected_track_volume()
            self._refresh_selected_clip_volume()
            return

        self.current_project_name = name
        self._ensure_final_product_track(self.current_project)
        self.timeline.set_project(self.current_project)
        self.current_pos_ms = 0
        self.start_input.setText("0.0")
        self.end_input.setText(ms_to_seconds_text(self.timeline.total_duration_ms()))
        self._refresh_timeline_ui()
        self._refresh_selected_track_volume()
        self._refresh_selected_clip_volume()

    def add_audio_files(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create a project first.")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Audio Files",
            "",
            "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac);;All Files (*)",
        )
        if not paths:
            return

        try:
            self._push_undo_state()
            self.stop_playback()
            self._ensure_final_product_track(project)
            for path in paths:
                audio = AudioSegment.from_file(path)
                clip = self._build_clip(
                    name=Path(path).name,
                    audio=audio,
                    start_ms=0,
                    spliced=False,
                    source_path=str(Path(path).expanduser().resolve()),
                    source_in_ms=0,
                    source_out_ms=len(audio),
                    reversed_audio=False,
                )
                project.tracks.append(Track(name=self._next_standard_track_name(project), clips=[clip]))

            self._mark_project_dirty()
            self.timeline.set_project(project)
            self.end_input.setText(ms_to_seconds_text(self.timeline.total_duration_ms()))
            self._refresh_timeline_ui()
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load files:\n{exc}")

    def _on_timeline_selection(self, track_idx: int, clip_idx: int):
        project = self.current_project
        if not project:
            return

        try:
            clip = project.tracks[track_idx].clips[clip_idx]
            self.start_input.setText(ms_to_seconds_text(clip.start_ms))
            self.end_input.setText(ms_to_seconds_text(clip.end_ms))
            self._refresh_selected_track_volume()
            self._refresh_selected_clip_volume()
        except Exception:
            pass

    def _on_timeline_playhead(self, ms: int):
        self.current_pos_ms = max(0, ms)
        self._refresh_position_ui()

    def _on_project_edited(self):
        project = self.current_project
        if self._prune_empty_tracks(project):
            self.timeline.set_project(project)
        self._mark_project_dirty()
        self._refresh_timeline_ui()
        self._refresh_selected_track_volume()
        self._refresh_selected_clip_volume()

    def rename_track(self, track_idx: int):
        project = self.current_project
        if not project or track_idx < 0 or track_idx >= len(project.tracks):
            return
        if getattr(project.tracks[track_idx], "is_final_product", False):
            QMessageBox.information(self, "Final Product Row", "The Final Product row name is fixed.")
            return

        current = project.tracks[track_idx].name
        new_name, ok = QInputDialog.getText(self, "Rename Track", "Track name:", text=current)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Track name cannot be empty.")
            return

        self._push_undo_state()
        project.tracks[track_idx].name = new_name
        self._mark_project_dirty()
        self.timeline.update()

    def _selected_clip_ref(self) -> tuple[Optional[Track], Optional[AudioClip], int, int]:
        project = self.current_project
        if not project:
            return None, None, -1, -1

        t_idx = self.timeline.selected_track
        c_idx = self.timeline.selected_clip
        if t_idx < 0 or c_idx < 0 or t_idx >= len(project.tracks):
            return None, None, -1, -1

        track = project.tracks[t_idx]
        if c_idx >= len(track.clips):
            return None, None, -1, -1

        return track, track.clips[c_idx], t_idx, c_idx

    def _get_selection_range(self) -> tuple[int, int]:
        start_ms = parse_time_to_ms(self.start_input.text())
        end_ms = parse_time_to_ms(self.end_input.text())
        if end_ms < start_ms:
            raise ValueError("End time must be >= start time.")
        return start_ms, end_ms

    def copy_selection(self):
        _, clip, _, _ = self._selected_clip_ref()
        if clip is None:
            QMessageBox.warning(self, "No Clip", "Select a clip first.")
            return

        try:
            start_ms, end_ms = self._get_selection_range()
            inter_start = max(start_ms, clip.start_ms)
            inter_end = min(end_ms, clip.end_ms)
            if inter_end <= inter_start:
                QMessageBox.warning(self, "Empty Selection", "Selection does not overlap selected clip.")
                return

            local_start = inter_start - clip.start_ms
            local_end = inter_end - clip.start_ms
            self.clipboard_audio = clip.audio[local_start:local_end]
            self.clipboard_name = f"{clip.name} (copy)"
            self.clipboard_volume_db = int(getattr(clip, "volume_db", 0) or 0)
            if clip.source_path:
                self.clipboard_source_path = clip.source_path
                self.clipboard_source_in_ms = max(0, clip.source_in_ms + local_start)
                self.clipboard_source_out_ms = max(self.clipboard_source_in_ms, clip.source_in_ms + local_end)
                self.clipboard_reversed = clip.reversed_audio
            else:
                self.clipboard_source_path = ""
                self.clipboard_source_in_ms = 0
                self.clipboard_source_out_ms = len(self.clipboard_audio)
                self.clipboard_reversed = False
        except Exception as exc:
            QMessageBox.warning(self, "Copy Error", str(exc))

    def cut_selection(self):
        track, clip, _, c_idx = self._selected_clip_ref()
        if clip is None or track is None:
            QMessageBox.warning(self, "No Clip", "Select a clip first.")
            return

        try:
            self._push_undo_state()
            start_ms, end_ms = self._get_selection_range()
            inter_start = max(start_ms, clip.start_ms)
            inter_end = min(end_ms, clip.end_ms)
            if inter_end <= inter_start:
                QMessageBox.warning(self, "Empty Selection", "Selection does not overlap selected clip.")
                return

            local_start = inter_start - clip.start_ms
            local_end = inter_end - clip.start_ms
            self.clipboard_audio = clip.audio[local_start:local_end]
            self.clipboard_name = f"{clip.name} (cut)"
            self.clipboard_volume_db = int(getattr(clip, "volume_db", 0) or 0)
            if clip.source_path:
                self.clipboard_source_path = clip.source_path
                self.clipboard_source_in_ms = max(0, clip.source_in_ms + local_start)
                self.clipboard_source_out_ms = max(self.clipboard_source_in_ms, clip.source_in_ms + local_end)
                self.clipboard_reversed = clip.reversed_audio
            else:
                self.clipboard_source_path = ""
                self.clipboard_source_in_ms = 0
                self.clipboard_source_out_ms = len(self.clipboard_audio)
                self.clipboard_reversed = False

            left = clip.audio[:local_start]
            right = clip.audio[local_end:]

            self.stop_playback()
            track.clips.pop(c_idx)
            new_clips = []
            if len(left) > 0:
                new_clips.append(
                    self._build_derived_clip(
                        parent=clip,
                        name=clip.name,
                        audio=left,
                        start_ms=clip.start_ms,
                        spliced=True,
                        local_start_ms=0,
                        local_end_ms=local_start,
                    )
                )
            if len(right) > 0:
                new_clips.append(
                    self._build_derived_clip(
                        parent=clip,
                        name=clip.name,
                        audio=right,
                        start_ms=inter_end,
                        spliced=True,
                        local_start_ms=local_end,
                        local_end_ms=len(clip.audio),
                    )
                )

            for offset, item in enumerate(new_clips):
                track.clips.insert(c_idx + offset, item)

            self._mark_project_dirty()
            self.timeline.set_project(self.current_project)
            self._refresh_timeline_ui()
        except Exception as exc:
            QMessageBox.warning(self, "Cut Error", str(exc))

    def delete_selection(self):
        track, clip, _, c_idx = self._selected_clip_ref()
        if clip is None or track is None:
            QMessageBox.warning(self, "No Clip", "Select a clip first.")
            return

        try:
            self._push_undo_state()
            start_ms, end_ms = self._get_selection_range()
            inter_start = max(start_ms, clip.start_ms)
            inter_end = min(end_ms, clip.end_ms)
            if inter_end <= inter_start:
                QMessageBox.warning(self, "Empty Selection", "Selection does not overlap selected clip.")
                return

            local_start = inter_start - clip.start_ms
            local_end = inter_end - clip.start_ms
            left = clip.audio[:local_start]
            right = clip.audio[local_end:]

            self.stop_playback()
            track.clips.pop(c_idx)
            new_clips = []
            if len(left) > 0:
                new_clips.append(
                    self._build_derived_clip(
                        parent=clip,
                        name=clip.name,
                        audio=left,
                        start_ms=clip.start_ms,
                        spliced=True,
                        local_start_ms=0,
                        local_end_ms=local_start,
                    )
                )
            if len(right) > 0:
                new_clips.append(
                    self._build_derived_clip(
                        parent=clip,
                        name=clip.name,
                        audio=right,
                        start_ms=inter_end,
                        spliced=True,
                        local_start_ms=local_end,
                        local_end_ms=len(clip.audio),
                    )
                )

            for offset, item in enumerate(new_clips):
                track.clips.insert(c_idx + offset, item)

            self._mark_project_dirty()
            self.timeline.set_project(self.current_project)
            self._refresh_timeline_ui()
        except Exception as exc:
            QMessageBox.warning(self, "Delete Error", str(exc))

    def paste_clipboard(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return
        if self.clipboard_audio is None or len(self.clipboard_audio) == 0:
            QMessageBox.warning(self, "Clipboard Empty", "Copy or cut first.")
            return

        t_idx = self.timeline.selected_track
        if t_idx < 0:
            t_idx = len(project.tracks)

        self._push_undo_state()
        track = self._ensure_track(project, t_idx)
        track.clips.append(
            self._build_clip(
                name=self.clipboard_name,
                audio=self.clipboard_audio,
                start_ms=max(0, self.current_pos_ms),
                spliced=False,
                source_path=self.clipboard_source_path,
                source_in_ms=self.clipboard_source_in_ms,
                source_out_ms=self.clipboard_source_out_ms if self.clipboard_source_out_ms > 0 else len(self.clipboard_audio),
                reversed_audio=self.clipboard_reversed,
                volume_db=self.clipboard_volume_db,
            )
        )

        self._mark_project_dirty()
        self.timeline.set_project(project)
        self._refresh_timeline_ui()

    def split_selected_clip(self):
        track, clip, _, c_idx = self._selected_clip_ref()
        if clip is None or track is None:
            QMessageBox.warning(self, "No Clip", "Select a clip first.")
            return

        split_at = self.current_pos_ms
        if split_at <= clip.start_ms or split_at >= clip.end_ms:
            QMessageBox.warning(self, "Invalid Split", "Playhead must be inside the selected clip.")
            return

        local = split_at - clip.start_ms
        left = clip.audio[:local]
        right = clip.audio[local:]

        self._push_undo_state()
        self.stop_playback()
        track.clips.pop(c_idx)
        track.clips.insert(
            c_idx,
            self._build_derived_clip(
                parent=clip,
                name=clip.name,
                audio=right,
                start_ms=split_at,
                spliced=True,
                local_start_ms=local,
                local_end_ms=len(clip.audio),
            ),
        )
        track.clips.insert(
            c_idx,
            self._build_derived_clip(
                parent=clip,
                name=clip.name,
                audio=left,
                start_ms=clip.start_ms,
                spliced=True,
                local_start_ms=0,
                local_end_ms=local,
            ),
        )

        self._mark_project_dirty()
        self.timeline.set_project(self.current_project)
        self._refresh_timeline_ui()

    def reverse_selected_clip(self):
        project = self.current_project
        track, clip, t_idx, _ = self._selected_clip_ref()
        if project is None or track is None or clip is None:
            QMessageBox.warning(self, "No Clip", "Select a clip first.")
            return

        reversed_audio = clip.audio.reverse()
        self._push_undo_state()
        new_clip = self._build_clip(
            name=f"{clip.name} (rev)",
            audio=reversed_audio,
            start_ms=clip.start_ms,
            spliced=clip.spliced,
            source_path=clip.source_path,
            source_in_ms=clip.source_in_ms,
            source_out_ms=clip.source_out_ms if clip.source_out_ms > 0 else len(clip.audio),
            reversed_audio=not clip.reversed_audio,
            volume_db=int(getattr(clip, "volume_db", 0) or 0),
        )

        new_track_index = t_idx + 1
        project.tracks.insert(new_track_index, Track(name=f"Track {new_track_index + 1} Rev", clips=[new_clip]))

        # Re-number standard tracks while preserving Final Product and Rev labels.
        next_track_num = 1
        for existing_track in project.tracks:
            if getattr(existing_track, "is_final_product", False):
                existing_track.name = self.FINAL_TRACK_NAME
                continue
            if "Rev" in existing_track.name:
                continue
            existing_track.name = f"Track {next_track_num}"
            next_track_num += 1

        self._mark_project_dirty()
        self.timeline.set_project(project)
        self._refresh_timeline_ui()

    def _capture_record_chunk(self, indata):
        if not self._recording:
            return
        self._recorded_chunks.append(indata.copy())
        self._record_level = peak_level(np, indata)

    def _record_input_callback(self, indata, _frames, _time_info, _status):
        self._capture_record_chunk(indata)

    def _record_monitor_callback(self, indata, outdata, _frames, _time_info, _status):
        self._capture_record_chunk(indata)
        if self.monitor_checkbox.isChecked():
            outdata[:] = indata
        else:
            outdata.fill(0)

    def toggle_recording(self):
        if self._recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if SD_IMPORT_ERROR:
            QMessageBox.warning(
                self,
                "Mic Unavailable",
                f"Microphone recording requires numpy and sounddevice.\n{SD_IMPORT_ERROR}",
            )
            return

        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return

        self.stop_playback()
        try:
            self._recorded_chunks = []
            self._record_level = 0.0
            device = self._selected_input_device()
            if self.monitor_checkbox.isChecked():
                stream_kwargs = {
                    "samplerate": self._record_sample_rate,
                    "channels": self._record_channels,
                    "dtype": self._record_dtype,
                    "callback": self._record_monitor_callback,
                }
                if device is not None:
                    stream_kwargs["device"] = (device, None)
                self._recording_stream = sd.Stream(
                    **stream_kwargs,
                )
            else:
                stream_kwargs = {
                    "samplerate": self._record_sample_rate,
                    "channels": self._record_channels,
                    "dtype": self._record_dtype,
                    "callback": self._record_input_callback,
                }
                if device is not None:
                    stream_kwargs["device"] = device
                self._recording_stream = sd.InputStream(**stream_kwargs)
            self._recording_stream.start()
            self._recording = True
            self.status_label.setText("Recording from microphone... click record again to stop.")
            self.record_btn.setIcon(make_icon(ICONS["stop"]))
            self.record_level_timer.start()
        except Exception as exc:
            self._recording = False
            self._recording_stream = None
            QMessageBox.critical(self, "Recording Error", str(exc))

    def stop_recording(self):
        if not self._recording:
            return

        self._recording = False
        self.record_level_timer.stop()
        if self._recording_stream is not None:
            try:
                self._recording_stream.stop()
                self._recording_stream.close()
            except Exception:
                pass
        self._recording_stream = None
        self.record_btn.setIcon(make_icon(ICONS["record"]))
        self.record_level_bar.setValue(0)

        if not self._recorded_chunks:
            self.status_label.setText("Recording stopped. No audio captured.")
            return

        project = self.current_project
        if not project:
            self.status_label.setText("Recording stopped, but no active project.")
            return

        try:
            self._push_undo_state()
            recorded_audio = chunks_to_audiosegment(np, self._recorded_chunks, self._record_sample_rate)
            clip = self._build_clip(
                name="Mic Recording",
                audio=recorded_audio,
                start_ms=max(0, self.current_pos_ms),
                spliced=False,
            )
            project.tracks.append(Track(name=self._next_standard_track_name(project, " Mic"), clips=[clip], muted=False))
            self._mark_project_dirty()
            self.timeline.set_project(project)
            self._refresh_timeline_ui()
            self.status_label.setText("Recording added as a new row.")
        except Exception as exc:
            QMessageBox.critical(self, "Recording Convert Error", str(exc))
        finally:
            self._recorded_chunks = []

    def toggle_selected_track_mute(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return

        selected_track = self.timeline.selected_track
        if selected_track < 0 or selected_track >= len(project.tracks):
            QMessageBox.warning(self, "No Row", "Select any clip in the row you want to mute/unmute.")
            return

        track = project.tracks[selected_track]
        self._push_undo_state()
        track.muted = not track.muted
        state = "muted" if track.muted else "unmuted"
        self.status_label.setText(f"{track.name} is now {state}.")
        self._mark_project_dirty()
        self.timeline.update()
        self._refresh_selected_track_volume()

    def _apply_clip_effects(self, clip: AudioClip, track: Optional[Track] = None) -> "AudioSegment":
        processed = resolve_clip_audio(clip, self._source_segment_cache)

        if self.fade_checkbox.isChecked() and clip.spliced:
            fade_ms = min(self._fade_ms(), len(processed) // 2)
            if fade_ms > 0:
                processed = processed.fade_in(fade_ms).fade_out(fade_ms)

        if self.noise_reduction_checkbox.isChecked():
            # Lightweight denoise approximation: remove low rumble and very high hiss.
            processed = high_pass_filter(processed, 120)
            processed = low_pass_filter(processed, 8500)

        boost_db = self._current_volume_boost()
        if boost_db > 0:
            processed = processed + boost_db
        if track is not None:
            track_volume_db = int(getattr(track, "volume_db", 0) or 0)
            if track_volume_db != 0:
                processed = processed + track_volume_db
        clip_volume_db = int(getattr(clip, "volume_db", 0) or 0)
        if clip_volume_db != 0:
            processed = processed + clip_volume_db

        return processed

    def _render_project_mix(self) -> "AudioSegment":
        project = self.current_project
        if not project:
            return AudioSegment.silent(duration=0)

        cache_key = (
            project.name,
            project.revision,
            tuple((track.muted, int(getattr(track, "volume_db", 0) or 0)) for track in project.tracks),
            tuple(
                (
                    clip.clip_id,
                    int(getattr(clip, "volume_db", 0) or 0),
                )
                for track in project.tracks
                for clip in track.clips
            ),
            self.fade_checkbox.isChecked(),
            self._fade_ms(),
            self.noise_reduction_checkbox.isChecked(),
            self._current_volume_boost(),
        )

        if self._mix_cache_key == cache_key and self._mix_cache is not None:
            return self._mix_cache

        total_ms = self.timeline.total_duration_ms()
        if total_ms <= 0:
            mix = AudioSegment.silent(duration=0)
        else:
                mix = AudioSegment.silent(duration=total_ms)
                for track in project.tracks:
                    if track.muted:
                        continue
                    for clip in track.clips:
                        mix = mix.overlay(self._apply_clip_effects(clip, track), position=clip.start_ms)

        self._mix_cache_key = cache_key
        self._mix_cache = mix
        return mix

    def _speed_with_pitch_change(self, segment: "AudioSegment", speed: float) -> "AudioSegment":
        altered = segment._spawn(segment.raw_data, overrides={"frame_rate": int(segment.frame_rate * speed)})
        return altered.set_frame_rate(segment.frame_rate)

    def _speed_preserve_pitch_ffmpeg(self, segment: "AudioSegment", speed: float) -> "AudioSegment":
        # ffmpeg atempo chain supports 0.5x..2x per stage; chain stages for wider ranges.
        chain = _atempo_chain(speed)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as src, tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as dst:
            src_path = src.name
            dst_path = dst.name

        try:
            segment.export(src_path, format="wav")
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                src_path,
                "-filter:a",
                chain,
                dst_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "ffmpeg speed conversion failed")
            return AudioSegment.from_file(dst_path)
        finally:
            for path in [src_path, dst_path]:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass

    def _speed_adjust(self, segment: "AudioSegment") -> "AudioSegment":
        speed = self._current_speed()
        if speed == 1.0:
            return segment

        if self.pitch_change_checkbox.isChecked():
            return self._speed_with_pitch_change(segment, speed)

        try:
            return self._speed_preserve_pitch_ffmpeg(segment, speed)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Speed Adjustment Warning",
                (
                    "Pitch-preserving speed adjustment failed; falling back to pitch-changing mode.\n"
                    f"Reason: {exc}"
                ),
            )
            return self._speed_with_pitch_change(segment, speed)

    def export_mix(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Mixed Audio",
            str(Path.home() / f"{project.name}_mix.wav"),
            "WAV (*.wav);;MP3 (*.mp3);;OGG (*.ogg);;FLAC (*.flac)",
        )
        if not out_path:
            return

        if self._export_thread is not None:
            QMessageBox.information(self, "Export In Progress", "An export is already running.")
            return

        self._export_progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, self)
        self._export_progress.setWindowTitle("Exporting")
        self._export_progress.setWindowModality(Qt.ApplicationModal)
        self._export_progress.setMinimumDuration(0)
        self._export_progress.setValue(0)
        self._export_progress.show()

        tracks_snapshot = copy.deepcopy(project.tracks)
        self._export_thread = QThread(self)
        self._export_worker = ExportWorker(
            tracks=tracks_snapshot,
            out_path=out_path,
            speed=self._current_speed(),
            pitch_changes_with_speed=self.pitch_change_checkbox.isChecked(),
            fade_spliced=self.fade_checkbox.isChecked(),
            fade_ms=self._fade_ms(),
            noise_reduction=self.noise_reduction_checkbox.isChecked(),
            volume_boost_db=self._current_volume_boost(),
        )
        self._export_worker.moveToThread(self._export_thread)

        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.finished.connect(self._cleanup_export_thread)
        self._export_worker.failed.connect(self._cleanup_export_thread)
        self._export_progress.canceled.connect(self._cancel_export)
        self._export_thread.start()

    def _on_export_progress(self, value: int, message: str):
        if self._export_progress is None:
            return
        self._export_progress.setLabelText(message)
        self._export_progress.setValue(max(0, min(100, value)))

    def _on_export_finished(self, out_path: str):
        if self._export_progress is not None:
            self._export_progress.setValue(100)
        QMessageBox.information(self, "Export Complete", f"Saved:\n{out_path}")

    def _on_export_failed(self, error_text: str):
        if self._export_progress is not None:
            self._export_progress.cancel()
        if error_text != "Export canceled.":
            QMessageBox.critical(self, "Export Error", error_text)

    def _cancel_export(self):
        if self._export_worker is not None:
            self._export_worker.cancel()

    def _cleanup_export_thread(self, *_args):
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait(1500)
            self._export_thread.deleteLater()
        if self._export_worker is not None:
            self._export_worker.deleteLater()
        if self._export_progress is not None:
            self._export_progress.deleteLater()
        self._export_thread = None
        self._export_worker = None
        self._export_progress = None

    def toggle_play_pause(self):
        project = self.current_project
        if not project:
            QMessageBox.warning(self, "No Project", "Create or select a project first.")
            return

        if self.is_playing:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self):
        base_mix = self._render_project_mix()
        if len(base_mix) == 0:
            return

        if self.current_pos_ms >= len(base_mix):
            self.current_pos_ms = 0

        base_segment = base_mix[self.current_pos_ms:]
        if len(base_segment) == 0:
            return

        play_segment = self._speed_adjust(base_segment)
        self.play_obj = _play_with_simpleaudio(play_segment)
        self.is_playing = True
        self.play_start_time = time.monotonic()
        self.play_start_pos_ms = self.current_pos_ms
        self._active_play_speed = self._current_speed()
        self._active_base_mix_len = len(base_mix)
        self.play_pause_btn.setIcon(make_icon(ICONS["pause"]))
        self.timer.start()

    def pause_playback(self):
        if not self.is_playing:
            return

        elapsed_ms = int((time.monotonic() - self.play_start_time) * 1000)
        advanced_ms = int(elapsed_ms * self._active_play_speed)
        self.current_pos_ms = min(self.play_start_pos_ms + advanced_ms, self._active_base_mix_len)

        if self.play_obj is not None:
            self.play_obj.stop()

        self.play_obj = None
        self.is_playing = False
        self.play_pause_btn.setIcon(make_icon(ICONS["play"]))
        self.timer.stop()
        self._refresh_position_ui()

    def stop_and_rewind(self):
        self.stop_playback()
        self.current_pos_ms = 0
        self.timeline.set_playhead(0)
        self._refresh_position_ui()

    def stop_playback(self):
        if self.play_obj is not None:
            self.play_obj.stop()
        self.play_obj = None
        self.is_playing = False
        self._active_play_speed = 1.0
        self._active_base_mix_len = 0
        self.play_pause_btn.setIcon(make_icon(ICONS["play"]))
        self.timer.stop()

    def seek_to(self, value: int):
        base_mix = self._render_project_mix()
        self.current_pos_ms = max(0, min(value, len(base_mix)))
        self.timeline.set_playhead(self.current_pos_ms)
        self._refresh_position_ui()

        if self.is_playing:
            self.stop_playback()
            self.start_playback()

    def _update_playback_ui(self):
        if not self.is_playing:
            return

        elapsed_ms = int((time.monotonic() - self.play_start_time) * 1000)
        advanced_ms = int(elapsed_ms * self._active_play_speed)
        self.current_pos_ms = min(self.play_start_pos_ms + advanced_ms, self._active_base_mix_len)
        self._refresh_position_ui()

        if self.play_obj is not None and not self.play_obj.is_playing():
            self.is_playing = False
            self.play_obj = None
            self.play_pause_btn.setIcon(make_icon(ICONS["play"]))
            self.timer.stop()

    def _refresh_timeline_ui(self):
        project = self.current_project
        if self._prune_empty_tracks(project):
            self.timeline.set_project(project)
        total = self.timeline.total_duration_ms()
        self.seek_slider.setMaximum(max(0, total))
        self.duration_label.setText(f"Duration: {ms_to_seconds_text(total)} s")
        self.current_pos_ms = min(self.current_pos_ms, total)
        self._refresh_position_ui()
        self.timeline.set_playhead(self.current_pos_ms)

    def _refresh_position_ui(self):
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(max(0, self.current_pos_ms))
        self.seek_slider.blockSignals(False)
        self.position_label.setText(f"Position: {ms_to_seconds_text(self.current_pos_ms)} s")
        # Keep the timeline marker locked to transport position during playback/seek/pause.
        self.timeline.set_playhead(self.current_pos_ms)

    def _update_record_level_meter(self):
        level = int(max(0.0, min(1.0, float(self._record_level))) * 100)
        self.record_level_bar.setValue(level)

    def closeEvent(self, event):
        self._is_closing = True
        self._autosave_timer.stop()
        if self._recording:
            self.stop_recording()
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._export_thread is not None:
            self._export_thread.quit()
            self._export_thread.wait(1500)
        self.stop_playback()
        self._save_projects_to_disk()
        event.accept()
