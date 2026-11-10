from pathlib import Path
from typing import Literal, Protocol

from .config import ModelRuntime, Settings
from .process import run_worker, WorkerFailed, WorkerTimeout, WorkerUnavailable

Language = Literal["ru", "en"]
MODELS = {"ru": "gigaam-multi", "en": "whisper"}


class AsrUnavailable(Exception):
    """Local recognition cannot be performed."""


class AsrTimeout(Exception):
    pass


class AsrAdapter(Protocol):
    def transcribe(self, audio: Path, language: Language) -> str:
        """Consume validated WAV synchronously; finish reading before returning.

        Process adapters wait for/terminate their worker before returning, so
        request-owned audio can be safely removed.
        """
        ...


class ProcessAdapter:
    language: Language
    worker_name: str

    def __init__(self, runtime: ModelRuntime, settings: Settings, *, worker: Path | None = None):
        self.runtime, self.settings = runtime, settings
        self.worker = worker or Path(__file__).resolve().parent.parent / "workers" / self.worker_name

    def transcribe(self, audio: Path, language: Language) -> str:
        if language != self.language:
            raise AsrUnavailable()
        python, weights = self.runtime.python, self.runtime.weights
        if (python is None or weights is None or not python.is_absolute() or not weights.is_absolute()
                or not python.is_file() or not weights.is_dir() or not self.worker.is_file()):
            raise AsrUnavailable()
        try:
            response = run_worker(python, self.worker.resolve(),
                                  {"audio": str(audio.resolve()), "weights": str(weights.resolve()), "language": language},
                                  timeout=self.settings.worker_timeout_seconds,
                                  output_limit=self.settings.max_worker_output_bytes,
                                  cpu_threads=self.settings.cpu_threads)
        except WorkerUnavailable as exc:
            raise AsrUnavailable() from exc
        except WorkerTimeout as exc:
            raise AsrTimeout() from exc
        except WorkerFailed as exc:
            raise RuntimeError("Local ASR worker failed") from exc
        return response["text"]


class WhisperAdapter(ProcessAdapter):
    language = "en"
    worker_name = "whisper_worker.py"


class GigaAMAdapter(ProcessAdapter):
    language = "ru"
    worker_name = "gigaam_worker.py"
