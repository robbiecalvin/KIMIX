from typing import Optional

from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from .editor_core import AudioClip, Project, ms_to_seconds_text


class TimelineWidget(QWidget):
    selection_changed = pyqtSignal(int, int)
    playhead_changed = pyqtSignal(int)
    clips_changed = pyqtSignal()
    track_rename_requested = pyqtSignal(int)
    edit_started = pyqtSignal()

    ROW_HEIGHT = 54
    HEADER_WIDTH = 220
    CLIP_HEIGHT = 34
    PX_PER_SEC = 100
    SNAP_THRESHOLD_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[Project] = None
        self.playhead_ms = 0
        self.selected_track = -1
        self.selected_clip = -1

        self._dragging = False
        self._drag_track = -1
        self._drag_clip = -1
        self._drag_offset_ms = 0
        self._dragging_row = False
        self._row_drag_track = -1

        self.setMinimumHeight(220)

    @property
    def px_per_ms(self) -> float:
        return self.PX_PER_SEC / 1000.0

    def ms_to_x(self, ms: int) -> int:
        return self.HEADER_WIDTH + int(ms * self.px_per_ms)

    def x_to_ms(self, x: int) -> int:
        return int(max(0, x - self.HEADER_WIDTH) / self.px_per_ms)

    def total_duration_ms(self) -> int:
        if not self.project:
            return 0
        value = 0
        for track in self.project.tracks:
            for clip in track.clips:
                value = max(value, clip.end_ms)
        return value

    def set_project(self, project: Optional[Project]):
        self.project = project
        self.selected_track = -1
        self.selected_clip = -1
        self.playhead_ms = 0
        self._recompute_size()
        self.update()

    def set_playhead(self, ms: int):
        self.playhead_ms = max(0, ms)
        self.update()

    def _recompute_size(self):
        duration = self.total_duration_ms()
        width = self.HEADER_WIDTH + int(duration * self.px_per_ms) + 320
        height = 220 if not self.project else max(220, (len(self.project.tracks) * self.ROW_HEIGHT) + 20)
        self.setMinimumSize(width, height)
        self.resize(width, height)

    def _clip_at_pos(self, pos: QPoint) -> tuple[int, int]:
        if not self.project:
            return -1, -1

        for t_idx, track in enumerate(self.project.tracks):
            row_top = t_idx * self.ROW_HEIGHT + 10
            for c_idx, clip in enumerate(track.clips):
                x1 = self.ms_to_x(clip.start_ms)
                x2 = self.ms_to_x(clip.end_ms)
                rect = QRect(x1, row_top + (self.ROW_HEIGHT - self.CLIP_HEIGHT) // 2, max(10, x2 - x1), self.CLIP_HEIGHT)
                if rect.contains(pos):
                    return t_idx, c_idx

        return -1, -1

    def _row_at_pos(self, pos: QPoint) -> int:
        if not self.project:
            return -1
        row_idx = int((pos.y() - 10) / self.ROW_HEIGHT)
        if 0 <= row_idx < len(self.project.tracks):
            return row_idx
        return -1

    def _draw_waveform(self, painter: QPainter, clip_rect: QRect, clip: AudioClip, muted: bool):
        if not clip.waveform_preview or len(clip.waveform_preview) < 2:
            return

        levels = clip.waveform_preview
        w = max(1, clip_rect.width())
        h = max(1, clip_rect.height())
        mid_y = clip_rect.y() + (h // 2)
        color = QColor("#e8efe9") if not muted else QColor("#b0b8c5")
        painter.setPen(QPen(color, 1))

        usable_h = max(2, h - 6)
        for px in range(w):
            idx = int((px / max(1, w - 1)) * (len(levels) - 1))
            amp = max(0.0, min(1.0, levels[idx]))
            half = int((usable_h * amp) / 2)
            x = clip_rect.x() + px
            painter.drawLine(x, mid_y - half, x, mid_y + half)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0b1220"))

        if not self.project:
            painter.setPen(QColor("#ffffff"))
            painter.drawText(24, 42, "Create a project, then add audio clips.")
            return

        for t_idx, track in enumerate(self.project.tracks):
            row_top = t_idx * self.ROW_HEIGHT + 10
            row_rect = QRect(0, row_top, self.width(), self.ROW_HEIGHT)
            if track.muted:
                bg = QColor("#0c1018") if t_idx % 2 == 0 else QColor("#0b0f16")
            else:
                bg = QColor("#111a2b") if t_idx % 2 == 0 else QColor("#0f1726")
            painter.fillRect(row_rect, bg)

            painter.setPen(QColor("#f4efe2") if not track.muted else QColor("#98a6ba"))
            track_label = f"{track.name} [MUTED]" if track.muted else track.name
            text_rect = QRect(10, row_top + 12, self.HEADER_WIDTH - 18, self.ROW_HEIGHT - 16)
            fm = QFontMetrics(painter.font())
            elided = fm.elidedText(track_label, Qt.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

            for c_idx, clip in enumerate(track.clips):
                x1 = self.ms_to_x(clip.start_ms)
                x2 = self.ms_to_x(clip.end_ms)
                clip_rect = QRect(x1, row_top + (self.ROW_HEIGHT - self.CLIP_HEIGHT) // 2, max(10, x2 - x1), self.CLIP_HEIGHT)

                if track.muted:
                    painter.setBrush(QColor("#4f5866"))
                elif t_idx == self.selected_track and c_idx == self.selected_clip:
                    painter.setBrush(QColor("#d18d53"))
                elif clip.spliced:
                    painter.setBrush(QColor("#c9a96a"))
                else:
                    painter.setBrush(QColor("#be7b46"))

                painter.setPen(QPen(QColor("#f4efe2"), 1))
                painter.drawRoundedRect(clip_rect, 4, 4)
                self._draw_waveform(painter, clip_rect.adjusted(3, 3, -3, -3), clip, track.muted)

                painter.setPen(QColor("#f7f7f7"))
                dur_text = f"{ms_to_seconds_text(len(clip.audio))}s"
                painter.drawText(clip_rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, dur_text)

        painter.setPen(QPen(QColor("#24334e"), 1))
        total_sec = int(self.total_duration_ms() / 1000) + 8
        for sec in range(total_sec):
            x = self.ms_to_x(sec * 1000)
            painter.drawLine(x, 0, x, self.height())
            painter.setPen(QColor("#8ea0bf"))
            painter.drawText(x + 2, 12, str(sec))
            painter.setPen(QPen(QColor("#24334e"), 1))

        x = self.ms_to_x(self.playhead_ms)
        painter.setPen(QPen(QColor("#ffecc4"), 2))
        painter.drawLine(x, 0, x, self.height())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.project:
            return

        row_idx = self._row_at_pos(event.pos())
        if event.x() <= self.HEADER_WIDTH and row_idx >= 0:
            self.edit_started.emit()
            self._dragging_row = True
            self._row_drag_track = row_idx
            self.selected_track = row_idx
            self.selected_clip = -1
            self.update()
            return

        t_idx, c_idx = self._clip_at_pos(event.pos())
        if t_idx >= 0:
            self.edit_started.emit()
            self.selected_track = t_idx
            self.selected_clip = c_idx
            self.selection_changed.emit(t_idx, c_idx)

            clip = self.project.tracks[t_idx].clips[c_idx]
            self._dragging = True
            self._drag_track = t_idx
            self._drag_clip = c_idx
            click_ms = self.x_to_ms(event.x())
            self._drag_offset_ms = max(0, click_ms - clip.start_ms)
            self.update()
            return

        self.playhead_ms = self.x_to_ms(event.x())
        self.playhead_changed.emit(self.playhead_ms)
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging_row and self.project:
            target_row = self._row_at_pos(event.pos())
            if target_row >= 0 and target_row != self._row_drag_track:
                tracks = self.project.tracks
                moved_track = tracks.pop(self._row_drag_track)
                tracks.insert(target_row, moved_track)
                self._row_drag_track = target_row
                self.selected_track = target_row
                self.selected_clip = -1
                self.clips_changed.emit()
                self.update()
            return

        if not self._dragging or not self.project:
            return

        track = self.project.tracks[self._drag_track]
        if not (0 <= self._drag_clip < len(track.clips)):
            return

        clip = track.clips[self._drag_clip]
        desired_start = max(0, self.x_to_ms(event.x()) - self._drag_offset_ms)

        # Hold Ctrl while dragging to keep intentional gaps and disable auto snap.
        snap_disabled = bool(event.modifiers() & Qt.ControlModifier)
        if not snap_disabled:
            nearest_left_end = None
            for idx, other in enumerate(track.clips):
                if idx == self._drag_clip:
                    continue
                if other.end_ms <= desired_start:
                    if nearest_left_end is None or other.end_ms > nearest_left_end:
                        nearest_left_end = other.end_ms
            if nearest_left_end is not None and abs(desired_start - nearest_left_end) <= self.SNAP_THRESHOLD_MS:
                desired_start = nearest_left_end

        clip.start_ms = desired_start
        self.playhead_ms = desired_start
        self.playhead_changed.emit(self.playhead_ms)
        self.clips_changed.emit()
        self._recompute_size()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_track = -1
            self._drag_clip = -1
            self._drag_offset_ms = 0
            self._dragging_row = False
            self._row_drag_track = -1

    def mouseDoubleClickEvent(self, event):
        if not self.project or event.button() != Qt.LeftButton:
            return
        if event.x() <= self.HEADER_WIDTH:
            row_idx = self._row_at_pos(event.pos())
            if row_idx >= 0:
                self.track_rename_requested.emit(row_idx)
