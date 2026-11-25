from collections.abc import Callable
from pathlib import Path

from .audio import AudioPreparationUnavailable, InvalidAudio, prepare_wav, validate_wav
from .config import Settings
from .process import WorkerFailed, WorkerTimeout, WorkerUnavailable, run_worker_process

# Exclude demuxers that interpret playlists, manifests or file lists.
INPUT_FORMATS = "wav,mp3,mov,flac,ogg,aac,aiff,amr,ac3,eac3,au,matroska,webm"


def prepare_masking_audio(source: Path, output: Path, settings: Settings,
                          checkpoint: Callable[[], None]) -> Path:
    ffmpeg = settings.ffmpeg_path
    try:
        return prepare_wav(source, output, settings, checkpoint=checkpoint)
    except InvalidAudio:
        if ffmpeg is None or not ffmpeg.is_absolute() or not ffmpeg.is_file():
            with source.open("rb") as stream:
                header = stream.read(12)
            if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
                raise
            raise AudioPreparationUnavailable() from None
    except AudioPreparationUnavailable:
        if ffmpeg is None or not ffmpeg.is_absolute() or not ffmpeg.is_file():
            raise

    # Decode a little beyond the duration limit so oversized input is rejected
    # by WAV validation instead of silently accepting a trimmed recording.
    command = [
        str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-n",
        "-protocol_whitelist", "file", "-format_whitelist", INPUT_FORMATS,
        "-err_detect", "explode", "-threads", "1", "-i", str(source),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        "-t", str(settings.max_duration_seconds + 1), "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", "-f", "wav", str(output),
    ]
    try:
        code, _ = run_worker_process(
            command, source.parent, None, timeout=settings.masking_timeout_seconds,
            output_limit=64 * 1024, checkpoint=checkpoint,
        )
    except WorkerTimeout as exc:
        raise TimeoutError() from exc
    except WorkerUnavailable as exc:
        raise AudioPreparationUnavailable() from exc
    except WorkerFailed as exc:
        raise InvalidAudio() from exc
    checkpoint()
    if code != 0 or not output.is_file():
        raise InvalidAudio()
    validate_wav(output, settings, checkpoint=checkpoint)
    return output
