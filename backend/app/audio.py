from pathlib import Path
from dataclasses import dataclass
from math import gcd
import struct
import wave

from .config import Settings


class InvalidAudio(Exception):
    pass


class AudioPreparationUnavailable(Exception):
    pass


@dataclass(frozen=True)
class WaveInfo:
    rate: int
    channels: int
    width: int
    frames: int


def validate_wav(path: Path, settings: Settings, *, normalized: bool = True) -> WaveInfo:
    """Validate actual PCM samples, not MIME or a client-supplied name."""
    try:
        with path.open("rb") as raw:
            header = raw.read(12)
        if (len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE"
                or struct.unpack("<I", header[4:8])[0] + 8 != path.stat().st_size):
            raise InvalidAudio()
        # wave.readframes alone can overlook an odd/truncated chunk or trailing
        # malformed metadata. Check all RIFF chunk boundaries before decoding.
        with path.open("rb") as raw:
            raw.seek(12)
            end = path.stat().st_size
            data_chunks = 0
            while raw.tell() < end:
                chunk = raw.read(8)
                if len(chunk) != 8:
                    raise InvalidAudio()
                size = struct.unpack("<I", chunk[4:])[0]
                if chunk[:4] == b"data":
                    data_chunks += 1
                    data_size = size
                next_chunk = raw.tell() + size + size % 2
                if next_chunk > end:
                    raise InvalidAudio()
                raw.seek(next_chunk)
            if data_chunks != 1:
                raise InvalidAudio()
        with wave.open(str(path), "rb") as audio:
            info = WaveInfo(audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes())
            if (audio.getcomptype() != "NONE" or info.channels not in (1, 2)
                    or info.width not in (1, 2, 3, 4) or not 8000 <= info.rate <= 192000
                    or data_size % (info.channels * info.width)):
                raise InvalidAudio()
            if normalized and (info.rate, info.channels, info.width) != (16000, 1, 2):
                raise InvalidAudio()
            if not 0 < info.frames <= settings.max_duration_seconds * info.rate:
                raise InvalidAudio()
            remaining = info.frames
            while remaining:
                count = min(remaining, 16000)
                if len(audio.readframes(count)) != count * info.channels * info.width:
                    raise InvalidAudio()
                remaining -= count
            return info
    except (wave.Error, EOFError, struct.error) as exc:
        raise InvalidAudio() from exc


def prepare_wav(source: Path, target: Path, settings: Settings) -> Path:
    """Return validated input or a separate normalized WAV; never rewrite source."""
    info = validate_wav(source, settings, normalized=False)
    if (info.rate, info.channels, info.width) == (16000, 1, 2):
        return source
    if source.resolve() == target.resolve():
        raise ValueError("Normalization target must differ from input")
    try:
        import numpy as np
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise AudioPreparationUnavailable() from exc
    with wave.open(str(source), "rb") as audio:
        raw = audio.readframes(info.frames)
    if info.width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128
    elif info.width == 3:
        triples = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = (values ^ 0x800000) - 0x800000
        samples = values.astype(np.float64) / 8388608
    else:
        dtype = "<i2" if info.width == 2 else "<i4"
        samples = np.frombuffer(raw, dtype=dtype).astype(np.float64) / (2 ** (info.width * 8 - 1))
    # Equal-weight downmix is explicit; no VAD, loudness normalization or trimming.
    samples = samples.reshape(-1, info.channels).mean(axis=1)
    if info.rate != 16000:
        divisor = gcd(info.rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, info.rate // divisor)
    pcm = np.clip(np.rint(samples * 32768), -32768, 32767).astype("<i2")
    with wave.open(str(target), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm.tobytes())
    validate_wav(target, settings)
    return target
