from base64 import b64encode
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal, Protocol
from collections.abc import Callable

from .audio import prepare_wav, validate_wav
from .config import Settings

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
    def process(self, prepared: Path, mode: MaskingMode, matrix: int, masked: Path,
                demasked: Path, checkpoint: Callable[[], None]) -> int:
        """Write both files, return applied matrix and finish using paths before returning."""
        ...


class CopyMaskingStub:
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


def process_upload(upload: BinaryIO, mode: MaskingMode, matrix: int, executor: MaskingExecutor,
                   settings: Settings, checkpoint: Callable[[], None]) -> dict:
    checkpoint()
    with TemporaryDirectory(prefix="audiomask-mask-", dir=settings.temp_directory) as directory:
        root = Path(directory)
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
        prepared = prepare_wav(source, root / "normalized.wav", settings, checkpoint=checkpoint)
        checkpoint()
        masked, demasked = root / "test-masked.wav", root / "test-demasked.wav"
        applied = executor.process(prepared, mode, matrix, masked, demasked, checkpoint)
        files = {}
        for name, path in (("masked", masked), ("demasked", demasked)):
            checkpoint()
            validate_wav(path, settings, checkpoint=checkpoint)
            files[name] = {"file_name": path.name, "media_type": "audio/wav",
                           "base64": b64encode(path.read_bytes()).decode("ascii")}
        checkpoint()
        return {"test_mode": True, "masking_performed": False, "notice": NOTICE,
                "mode": mode, "selected_matrix": matrix, "applied_matrix": applied, **files}
