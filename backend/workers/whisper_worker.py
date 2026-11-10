"""Local faster-whisper small multilingual, CPU INT8. Not run by unit tests."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import main


def transcribe(audio: Path, weights: Path) -> str:
    # Require complete local assets; do not fall back to a Hub model identifier.
    for name in ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json"):
        if not (weights / name).is_file():
            raise FileNotFoundError()
    from faster_whisper import WhisperModel
    model = WhisperModel(str(weights), device="cpu", compute_type="int8",
                         local_files_only=True, cpu_threads=int(os.environ.get("AUDIOMASK_CPU_THREADS", "4")))
    if not model.model.is_multilingual:
        raise ValueError("Expected multilingual Whisper weights")
    segments, _ = model.transcribe(str(audio), language="en", task="transcribe", vad_filter=False)
    return "".join(segment.text for segment in segments).strip()


if __name__ == "__main__":
    main(transcribe, "en")
