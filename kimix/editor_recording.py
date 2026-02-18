from .audio_engine import AudioSegment


def list_input_devices(sd_module):
    devices = []
    try:
        for index, device in enumerate(sd_module.query_devices()):
            max_channels = int(device.get("max_input_channels", 0))
            if max_channels > 0:
                label = f"{device.get('name', f'Input {index}')} (ch {max_channels})"
                devices.append((index, label))
    except Exception:
        return []
    return devices


def peak_level(np_module, indata) -> float:
    try:
        peak = float(np_module.max(np_module.abs(indata)))
    except Exception:
        peak = 0.0
    return max(0.0, min(1.0, peak))


def chunks_to_audiosegment(np_module, chunks, sample_rate: int):
    audio_np = np_module.concatenate(chunks, axis=0)
    channels = int(audio_np.shape[1]) if audio_np.ndim > 1 else 1
    if np_module.issubdtype(audio_np.dtype, np_module.floating):
        audio_np = np_module.clip(audio_np, -1.0, 1.0)
        pcm_i16 = (audio_np * 32767.0).astype(np_module.int16)
    else:
        pcm_i16 = audio_np.astype(np_module.int16, copy=False)
    raw_pcm = pcm_i16.tobytes()
    return AudioSegment(
        data=raw_pcm,
        sample_width=2,
        frame_rate=sample_rate,
        channels=channels,
    )
