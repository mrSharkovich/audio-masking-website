from base64 import b64encode
from pathlib import Path
from shutil import copyfile
from stat import S_ISREG
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal, Protocol
from collections.abc import Callable

from .audio import InvalidAudio, validate_wav
from .config import Settings
from .masking_audio import prepare_masking_audio
from .process import WorkerFailed, WorkerTimeout, decode_worker_json, run_worker_process

MaskingMode = Literal["one-sided", "two-sided"]
MODES = ("one-sided", "two-sided")
MATRICES = (4, 8, 16, 32, 64, 128, 256, 512)
NOTICE = "Тестовый режим. Маскирование не выполняется. Аудиофайлы возвращаются без изменения звучания"


class UploadTooLarge(Exception):
    pass


class EmptyUpload(Exception):
    pass


class MaskingCancelled(Exception):
    pass


class MaskingExecutor(Protocol):
    test_mode: bool

    def process(self, prepared: Path, mode: MaskingMode, matrix: int, masked: Path,
                demasked: Path, checkpoint: Callable[[], None]) -> int:
        """Write both files, return applied matrix and finish using paths before returning."""
        ...


class CopyMaskingStub:
    test_mode = True

    def __init__(self, settings: Settings):
        self.settings = settings

    def process(self, prepared: Path, mode: MaskingMode, matrix: int, masked: Path,
                demasked: Path, checkpoint: Callable[[], None]) -> int:
        frames = validate_wav(prepared, self.settings, checkpoint=checkpoint).frames
        maximum = next((size for size in MATRICES[:-1] if frames <= size * size), MATRICES[-1])
        for output in (masked, demasked):
            checkpoint()
            copyfile(prepared, output)
        return min(matrix, maximum)


class PythonMaskingRunner:
    test_mode = False

    # Wait for containment before executing configured code. Consume only the
    # gate byte so the script receives the original JSON through ordinary stdin.
    _BOOTSTRAP = """\
import os
import runpy
import sys
if os.read(0, 1) != b'\\n':
    raise SystemExit(1)
script = sys.argv[1]
sys.argv[:] = [script]
sys.path.insert(0, os.path.dirname(script))
runpy.run_path(script, run_name='__main__')
"""

    def __init__(self, python: Path, script: Path, timeout: float):
        self.python, self.script, self.timeout = python, script, timeout

    def process(self, prepared: Path, mode: MaskingMode, matrix: int, masked: Path,
                demasked: Path, checkpoint: Callable[[], None]) -> int:
        request = {"protocol_version": 1, "input_path": str(prepared),
                   "masked_output_path": str(masked), "demasked_output_path": str(demasked),
                   "mode": mode, "matrix_size": matrix}
        try:
            code, output = run_worker_process(
                [str(self.python), "-I", "-u", "-c", self._BOOTSTRAP, str(self.script)],
                self.script.parent, request, timeout=self.timeout, output_limit=64 * 1024,
                checkpoint=checkpoint, startup_gate=True,
            )
        except WorkerTimeout as exc:
            raise TimeoutError() from exc
        if code != 0:
            raise WorkerFailed()
        result = decode_worker_json(output)
        version, applied = result.get("protocol_version"), result.get("applied_matrix_size")
        if (set(result) != {"protocol_version", "status", "applied_matrix_size"}
                or type(version) is not int or version != 1 or result["status"] != "ok"
                or type(applied) is not int or applied not in MATRICES):
            raise WorkerFailed()
        return applied


def configured_masking_executor(settings: Settings) -> MaskingExecutor | None:
    python, script = settings.masking_runner_python, settings.masking_runner_script
    if settings.masking_stub:
        return CopyMaskingStub(settings) if python is None and script is None else None
    if (python is not None and script is not None and python.is_absolute() and script.is_absolute()
            and python.is_file() and script.is_file()):
        return PythonMaskingRunner(python, script, settings.masking_timeout_seconds)
    return None


def process_upload(upload: BinaryIO, mode: MaskingMode, matrix: int, executor: MaskingExecutor,
                   settings: Settings, checkpoint: Callable[[], None]) -> dict:
    checkpoint()
    with TemporaryDirectory(prefix="audiomask-mask-", dir=settings.temp_directory) as directory:
        root = Path(directory).resolve()
        source = root / "source.wav"
        size = 0
        with source.open("wb") as target:
            while chunk := upload.read(64 * 1024):
                checkpoint()
                size += len(chunk)
                if size > settings.max_file_bytes:
                    raise UploadTooLarge()
                target.write(chunk)
        if not size:
            raise EmptyUpload()
        prepared = prepare_masking_audio(source, root / "normalized.wav", settings, checkpoint)
        checkpoint()
        prefix = "test-" if executor.test_mode else ""
        masked, demasked = root / f"{prefix}masked.wav", root / f"{prefix}demasked.wav"
        applied = executor.process(prepared, mode, matrix, masked, demasked, checkpoint)
        files = {}
        for name, path in (("masked", masked), ("demasked", demasked)):
            checkpoint()
            try:
                info = path.lstat()
                limit = max(settings.max_file_bytes, 44 + 32000 * settings.max_duration_seconds)
                if not S_ISREG(info.st_mode) or info.st_size > limit:
                    raise InvalidAudio()
                validate_wav(path, settings, checkpoint=checkpoint)
            except TimeoutError:
                raise
            except (InvalidAudio, OSError) as exc:
                raise WorkerFailed() from exc
            files[name] = {"file_name": path.name, "media_type": "audio/wav",
                           "base64": b64encode(path.read_bytes()).decode("ascii")}
        checkpoint()
        return {"test_mode": executor.test_mode, "masking_performed": not executor.test_mode,
                "notice": NOTICE if executor.test_mode else None,
                "mode": mode, "selected_matrix": matrix, "applied_matrix": applied, **files}
