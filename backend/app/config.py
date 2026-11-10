from dataclasses import dataclass, field
import os
import math
from pathlib import Path


@dataclass(frozen=True)
class ModelRuntime:
    # Trusted server configuration, never supplied by an HTTP client.
    python: Path | None = None
    weights: Path | None = None


def runtime_from_env(prefix: str) -> ModelRuntime:
    def path(suffix: str) -> Path | None:
        value = os.environ.get(f"AUDIOMASK_{prefix}_{suffix}")
        return Path(value) if value else None
    return ModelRuntime(path("PYTHON"), path("WEIGHTS"))


@dataclass(frozen=True)
class Settings:
    max_file_bytes: int = 25 * 1024 * 1024
    max_duration_seconds: int = 300
    temp_directory: Path | None = None
    gigaam: ModelRuntime = field(default_factory=ModelRuntime)
    whisper: ModelRuntime = field(default_factory=ModelRuntime)
    worker_timeout_seconds: float = 120
    max_concurrent_asr: int = 1
    max_worker_output_bytes: int = 256 * 1024
    cpu_threads: int = 4

    def __post_init__(self) -> None:
        if self.max_file_bytes <= 0 or self.max_duration_seconds <= 0:
            raise ValueError("Upload limits must be positive")
        if (not math.isfinite(self.worker_timeout_seconds) or self.worker_timeout_seconds <= 0
                or self.max_concurrent_asr <= 0 or self.max_worker_output_bytes <= 0 or self.cpu_threads <= 0):
            raise ValueError("Worker limits must be positive and finite")

    @classmethod
    def from_env(cls) -> "Settings":
        temp = os.environ.get("AUDIOMASK_TEMP_DIRECTORY")
        return cls(
            max_file_bytes=int(os.environ.get("AUDIOMASK_MAX_FILE_BYTES", 25 * 1024 * 1024)),
            max_duration_seconds=int(os.environ.get("AUDIOMASK_MAX_DURATION_SECONDS", 300)),
            temp_directory=Path(temp) if temp else None,
            gigaam=runtime_from_env("GIGAAM"),
            whisper=runtime_from_env("WHISPER"),
            worker_timeout_seconds=float(os.environ.get("AUDIOMASK_WORKER_TIMEOUT_SECONDS", 120)),
            max_concurrent_asr=int(os.environ.get("AUDIOMASK_MAX_CONCURRENT_ASR", 1)),
            max_worker_output_bytes=int(os.environ.get("AUDIOMASK_MAX_WORKER_OUTPUT_BYTES", 256 * 1024)),
            cpu_threads=int(os.environ.get("AUDIOMASK_CPU_THREADS", 4)),
        )
