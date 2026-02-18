from dataclasses import dataclass, field
from typing import Optional


def ms_to_seconds_text(ms: int) -> str:
    return f"{ms / 1000:.2f}"


def parse_time_to_ms(text: str) -> int:
    text = text.strip()
    if not text:
        raise ValueError("Time is empty.")

    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError("Use mm:ss or seconds.")
        minutes = float(parts[0])
        seconds = float(parts[1])
        total_seconds = (minutes * 60) + seconds
    else:
        total_seconds = float(text)

    if total_seconds < 0:
        raise ValueError("Time must be non-negative.")
    return int(total_seconds * 1000)


@dataclass
class AudioClip:
    clip_id: int
    name: str
    audio: object
    start_ms: int
    spliced: bool = False
    media_filename: str = ""
    waveform_preview: Optional[list[float]] = None
    source_path: str = ""
    source_in_ms: int = 0
    source_out_ms: int = 0
    reversed_audio: bool = False
    volume_db: int = 0

    @property
    def end_ms(self) -> int:
        return self.start_ms + len(self.audio)


@dataclass
class Track:
    name: str
    clips: list[AudioClip] = field(default_factory=list)
    muted: bool = False
    volume_db: int = 0


@dataclass
class Project:
    name: str
    tracks: list[Track] = field(default_factory=list)
    revision: int = 0
