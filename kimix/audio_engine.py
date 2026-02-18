import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal

AudioSegment = None
_play_with_simpleaudio = None
high_pass_filter = None
low_pass_filter = None
PYDUB_IMPORT_ERROR = ""
if sys.version_info >= (3, 13):
    PYDUB_IMPORT_ERROR = (
        "This app requires Python 3.11 or 3.12 because pydub depends on "
        "the removed stdlib module 'audioop' on Python 3.13+."
    )
else:
    try:
        from pydub import AudioSegment
        from pydub.effects import high_pass_filter, low_pass_filter
        from pydub.playback import _play_with_simpleaudio
    except Exception as exc:
        PYDUB_IMPORT_ERROR = str(exc)


def atempo_chain(speed: float) -> str:
    factors = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def resolve_clip_audio(clip, source_segment_cache=None):
    source_path = str(getattr(clip, "source_path", "") or "")
    if not source_path or AudioSegment is None:
        return clip.audio
    source_in_ms = max(0, int(getattr(clip, "source_in_ms", 0) or 0))
    source_out_ms = int(getattr(clip, "source_out_ms", 0) or 0)
    reversed_audio = bool(getattr(clip, "reversed_audio", False))
    key = (source_path, source_in_ms, source_out_ms, reversed_audio)
    if source_segment_cache is not None:
        cached = source_segment_cache.get(key)
        if cached is not None:
            return cached
    try:
        path = Path(source_path).expanduser()
        if not path.exists():
            return clip.audio
        source = AudioSegment.from_file(str(path))
        if source_out_ms <= 0:
            source_out_ms = len(source)
        source_out_ms = max(source_in_ms, min(len(source), source_out_ms))
        segment = source[source_in_ms:source_out_ms]
        if reversed_audio:
            segment = segment.reverse()
        if source_segment_cache is not None:
            source_segment_cache[key] = segment
        return segment
    except Exception:
        return clip.audio


class ExportWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        tracks,
        out_path: str,
        speed: float,
        pitch_changes_with_speed: bool,
        fade_spliced: bool,
        fade_ms: int,
        noise_reduction: bool,
        volume_boost_db: int,
    ):
        super().__init__()
        self.tracks = tracks
        self.out_path = out_path
        self.speed = speed
        self.pitch_changes_with_speed = pitch_changes_with_speed
        self.fade_spliced = fade_spliced
        self.fade_ms = max(0, int(fade_ms))
        self.noise_reduction = noise_reduction
        self.volume_boost_db = int(volume_boost_db)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _apply_clip_effects(self, clip, track):
        processed = resolve_clip_audio(clip)
        if self.fade_spliced and clip.spliced:
            fms = min(self.fade_ms, len(processed) // 2)
            if fms > 0:
                processed = processed.fade_in(fms).fade_out(fms)
        if self.noise_reduction and high_pass_filter is not None and low_pass_filter is not None:
            processed = high_pass_filter(processed, 120)
            processed = low_pass_filter(processed, 8500)
        if self.volume_boost_db > 0:
            processed = processed + self.volume_boost_db
        track_volume_db = int(getattr(track, "volume_db", 0) or 0)
        if track_volume_db != 0:
            processed = processed + track_volume_db
        clip_volume_db = int(getattr(clip, "volume_db", 0) or 0)
        if clip_volume_db != 0:
            processed = processed + clip_volume_db
        return processed

    def _speed_with_pitch_change(self, segment, speed: float):
        altered = segment._spawn(segment.raw_data, overrides={"frame_rate": int(segment.frame_rate * speed)})
        return altered.set_frame_rate(segment.frame_rate)

    def _speed_preserve_pitch_ffmpeg(self, segment, speed: float):
        chain = atempo_chain(speed)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as src, tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as dst:
            src_path = src.name
            dst_path = dst.name
        try:
            segment.export(src_path, format="wav")
            cmd = ["ffmpeg", "-y", "-i", src_path, "-filter:a", chain, dst_path]
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

    def _speed_adjust(self, segment):
        if self.speed == 1.0:
            return segment
        if self.pitch_changes_with_speed:
            return self._speed_with_pitch_change(segment, self.speed)
        return self._speed_preserve_pitch_ffmpeg(segment, self.speed)

    def run(self):
        try:
            if self._cancel:
                self.failed.emit("Export canceled.")
                return

            total_ms = 0
            total_clips = 0
            for track in self.tracks:
                for clip in track.clips:
                    total_ms = max(total_ms, clip.end_ms)
                    if not track.muted:
                        total_clips += 1

            if total_ms <= 0:
                mix = AudioSegment.silent(duration=0)
            else:
                mix = AudioSegment.silent(duration=total_ms)
                processed_count = 0
                for track in self.tracks:
                    if track.muted:
                        continue
                    for clip in track.clips:
                        if self._cancel:
                            self.failed.emit("Export canceled.")
                            return
                        mix = mix.overlay(self._apply_clip_effects(clip, track), position=clip.start_ms)
                        processed_count += 1
                        pct = int((processed_count / max(1, total_clips)) * 70)
                        self.progress.emit(pct, "Mixing tracks...")

            if self._cancel:
                self.failed.emit("Export canceled.")
                return

            self.progress.emit(80, "Applying speed settings...")
            mix = self._speed_adjust(mix)
            if self._cancel:
                self.failed.emit("Export canceled.")
                return

            self.progress.emit(90, "Writing output file...")
            ext = Path(self.out_path).suffix.lower().lstrip(".")
            if not ext:
                raise ValueError("Output path is missing file extension.")
            mix.export(self.out_path, format=ext)
            self.progress.emit(100, "Done")
            self.finished.emit(self.out_path)
        except Exception as exc:
            self.failed.emit(str(exc))
