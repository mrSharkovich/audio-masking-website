from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore, Event
from time import monotonic
import math

from anyio import create_task_group
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .audio import AudioPreparationUnavailable, InvalidAudio, validate_wav
from .config import Settings
from .masking_audio import prepare_masking_audio
from .process import WorkerFailed, WorkerTimeout, WorkerUnavailable, decode_worker_json, run_worker_process

METRICS = {"PESQ": (1.0, 4.65, 4000), "ViSQOL": (1.0, 5.0, 16000),
           "ViSQOL_LATTICE": (1.0, 5.0, 16000)}
RECORDINGS = ("original", "masked", "demasked")
PAIRS = {
    "masked": ("original", "masked"),
    "demasked": ("original", "demasked"),
    "masked_demasked": ("masked", "demasked"),
}
SCRIPT = Path(__file__).resolve().parents[1] / "workers" / "quality_worker.py"


class QualityCancelled(Exception):
    pass


class UploadProblem(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def failed(status: str, message: str) -> dict:
    return {"status": status, "message": message}


def run_metric(settings: Settings, metric: str, checkpoint: Callable[[], None],
               reference: Path | None = None, degraded: Path | None = None) -> dict:
    checkpoint()
    python = settings.quality_python
    unavailable = failed("unavailable", "Метрика не подключена или недоступна.")
    if python is None or not python.is_absolute() or not python.is_file():
        return unavailable

    request = {"metric": metric, "reference": str(reference) if reference else None,
               "degraded": str(degraded) if degraded else None}
    try:
        code, output = run_worker_process(
            [str(python), "-I", "-u", str(SCRIPT)], SCRIPT.parent, request,
            timeout=settings.quality_timeout_seconds, output_limit=settings.max_worker_output_bytes,
            checkpoint=checkpoint,
        )
        if code == 3:
            return unavailable
        if code == 4:
            return failed("error", "Для расчёта нужен речевой сигнал с изменяющейся амплитудой.")
        if code != 0:
            raise WorkerFailed()
        result = decode_worker_json(output)
        if reference is None:
            if result == {"ready": True} and result["ready"] is True:
                return {"status": "available"}
        else:
            value = result.get("value")
            lower, upper, _ = METRICS[metric]
            if set(result) == {"value"} and type(value) in (int, float) and lower <= value <= upper and math.isfinite(value):
                return {"status": "success", "value": value}
        raise WorkerFailed()
    except WorkerUnavailable:
        return unavailable
    except WorkerTimeout:
        return failed("error", "Истекло время расчёта метрики.")
    except WorkerFailed:
        return failed("error", "Не удалось получить корректную оценку.")


def evaluate_uploads(uploads, pairs: list[str], settings: Settings, output_limit: int,
                     checkpoint: Callable[[], None], preparation_checkpoint: Callable[[], None]) -> dict:
    with TemporaryDirectory(prefix="audiomask-quality-", dir=settings.temp_directory) as directory:
        root = Path(directory).resolve()
        paths, lengths = {}, {}
        for name in uploads:
            preparation_checkpoint()
            path = root / f"{name}.wav"
            limit = settings.max_file_bytes if name == "original" else output_limit
            size = 0
            with path.open("wb") as target:
                while chunk := uploads[name].file.read(64 * 1024):
                    preparation_checkpoint()
                    size += len(chunk)
                    if size > limit:
                        raise UploadProblem(413, "upload_too_large", "Аудиофайл превышает допустимый размер.")
                    target.write(chunk)
            if not size:
                raise UploadProblem(422, "empty_audio", "Одна из аудиозаписей пуста.")
            if name == "original":
                path = prepare_masking_audio(path, root / "normalized.wav", settings, preparation_checkpoint)
            paths[name] = path
            lengths[name] = validate_wav(path, settings, checkpoint=preparation_checkpoint).frames

        comparisons = {}
        for pair in pairs:
            reference, degraded = PAIRS[pair]
            scores = {}
            for metric, (_, _, minimum_frames) in METRICS.items():
                checkpoint()
                if lengths[reference] != lengths[degraded]:
                    item = failed("error", "Длительности записей после подготовки различаются.")
                elif lengths[degraded] < minimum_frames:
                    item = failed("error", "Запись слишком короткая для этой метрики.")
                else:
                    item = run_metric(settings, metric, checkpoint, paths[reference], paths[degraded])
                scores[metric] = item
            comparisons[pair] = scores
        return {"comparisons": comparisons}


def quality_router(settings: Settings, output_limit: int) -> APIRouter:
    router = APIRouter(prefix="/api/quality")
    slot = BoundedSemaphore(1)

    def error(status: int, code: str, message: str):
        return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)

    async def execute(request: Request, operation):
        if not slot.acquire(blocking=False):
            return error(503, "quality_busy", "Сервис оценки занят. Повторите запрос позже.")
        cancelled = Event()

        def checkpoint():
            if cancelled.is_set():
                raise QualityCancelled()

        async def watch_disconnect():
            while (await request.receive())["type"] != "http.disconnect":
                pass
            cancelled.set()

        try:
            failure = None
            async with create_task_group() as group:
                group.start_soon(watch_disconnect)
                try:
                    result = await run_in_threadpool(operation, checkpoint)
                except Exception as exc:
                    failure = exc
                finally:
                    group.cancel_scope.cancel()
            checkpoint()
            if failure is not None:
                raise failure
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except QualityCancelled:
            return Response(status_code=499)
        except UploadProblem as exc:
            return error(exc.status, exc.code, exc.message)
        except InvalidAudio:
            return error(415, "invalid_audio", "Не удалось прочитать одну из аудиозаписей.")
        except AudioPreparationUnavailable:
            return error(503, "audio_preparation_unavailable", "Подготовка исходного аудио недоступна.")
        except TimeoutError:
            return error(504, "quality_timeout", "Истекло время подготовки аудио.")
        except Exception:
            return error(500, "quality_failed", "Не удалось выполнить оценку качества.")
        finally:
            slot.release()

    @router.get("/status")
    async def status(request: Request):
        def probe(checkpoint):
            return {"metrics": {metric: run_metric(settings, metric, checkpoint) for metric in METRICS}}

        return await execute(request, probe)

    @router.post("/evaluate")
    async def evaluate(request: Request):
        try:
            async with request.form(max_files=3, max_fields=3, max_part_size=1024) as form:
                pairs = form.getlist("pairs")
                if (not pairs or any(not isinstance(pair, str) or pair not in PAIRS for pair in pairs)
                        or len(set(pairs)) != len(pairs)):
                    return error(422, "invalid_pairs", "Выберите одну или несколько допустимых пар аудиозаписей.")
                needed = {name for pair in pairs for name in PAIRS[pair]}
                if (set(form) != needed | {"pairs"} or len(form.multi_items()) != len(needed) + len(pairs)
                        or any(not isinstance(form[name], UploadFile) for name in needed)):
                    raise HTTPException(422)

                def operation(checkpoint):
                    def preparation_checkpoint():
                        checkpoint()
                        if monotonic() >= request.scope["audiomask.quality_deadline"]:
                            raise TimeoutError()

                    uploads = {name: form[name] for name in RECORDINGS if name in needed}
                    return evaluate_uploads(uploads, pairs, settings, output_limit, checkpoint, preparation_checkpoint)

                return await execute(request, operation)
        except HTTPException:
            return error(422, "invalid_form", "Передайте по одному аудиофайлу для каждой записи в выбранных парах.")

    return router
