from pathlib import Path

from .audio_engine import AudioSegment


def clip_metadata_dict(clip, media_filename: str) -> dict:
    return {
        "clip_id": clip.clip_id,
        "name": clip.name,
        "start_ms": clip.start_ms,
        "spliced": clip.spliced,
        "media_filename": media_filename,
        "source_path": clip.source_path,
        "source_in_ms": clip.source_in_ms,
        "source_out_ms": clip.source_out_ms,
        "reversed_audio": clip.reversed_audio,
        "volume_db": int(getattr(clip, "volume_db", 0) or 0),
    }


def load_clip_audio_from_sources(clip_obj: dict, media_path: Path):
    source_path = str(clip_obj.get("source_path", "") or "")
    source_in_ms = int(clip_obj.get("source_in_ms", 0) or 0)
    source_out_ms = int(clip_obj.get("source_out_ms", 0) or 0)
    reversed_audio = bool(clip_obj.get("reversed_audio", False))
    volume_db = int(clip_obj.get("volume_db", 0) or 0)

    audio = None
    if media_path.exists():
        audio = AudioSegment.from_file(media_path)
    elif source_path and Path(source_path).exists():
        source_seg = AudioSegment.from_file(source_path)
        if source_out_ms <= 0:
            source_out_ms = len(source_seg)
        start_ms = max(0, source_in_ms)
        end_ms = max(start_ms, min(len(source_seg), source_out_ms))
        audio = source_seg[start_ms:end_ms]
        if reversed_audio:
            audio = audio.reverse()

    return {
        "audio": audio,
        "source_path": source_path,
        "source_in_ms": source_in_ms,
        "source_out_ms": source_out_ms,
        "reversed_audio": reversed_audio,
        "volume_db": volume_db,
    }
