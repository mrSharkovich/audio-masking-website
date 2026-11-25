from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping
from threading import BoundedSemaphore, Event
from time import monotonic
from ipaddress import ip_address
from contextlib import nullcontext

from anyio import create_task_group, fail_after

from fastapi import FastAPI, Request
from starlette.datastructures import UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .asr import AsrAdapter, AsrUnavailable, AsrFfmpegUnavailable, AsrTimeout, Language, MODELS, WhisperAdapter, GigaAMAdapter
from .audio import InvalidAudio, prepare_wav, AudioPreparationUnavailable
from .config import Settings
from .masking import (EmptyUpload, MaskingCancelled, MATRICES, MODES, NOTICE,
                      UploadTooLarge, configured_masking_executor, process_upload)
from .process import WorkerFailed, WorkerUnavailable
from .quality import quality_router


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class BodyLimit:
    """Bound multipart data before parsing/spooling, even without Content-Length."""
    def __init__(self, app, limit: int, masking_timeout: float, quality_limit: int, quality_timeout: float):
        self.app, self.limit = app, limit
        self.masking_timeout = masking_timeout
        self.quality_limit, self.quality_timeout = quality_limit, quality_timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] not in {"/api/asr/transcribe", "/api/masking/process", "/api/quality/evaluate"}:
            return await self.app(scope, receive, send)
        masking = scope["path"] == "/api/masking/process"
        quality = scope["path"] == "/api/quality/evaluate"
        timeout = self.quality_timeout if quality else self.masking_timeout
        limit = self.quality_limit if quality else self.limit
        if masking:
            scope["audiomask.masking_deadline"] = monotonic() + self.masking_timeout
        if quality:
            scope["audiomask.quality_deadline"] = monotonic() + timeout
        body = bytearray()
        limit_response = None
        try:
            with fail_after(timeout) if masking or quality else nullcontext():
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > limit:
                        limit_response = error(413, "upload_too_large", "Превышен допустимый размер запроса.")
                        break
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            if quality:
                return await error(504, "quality_timeout", "Истекло время загрузки аудио.")(scope, receive, send)
            if not masking:
                raise
            limit_response = error(504, "masking_timeout", "Истекло время загрузки аудиофайла.")
        if limit_response is not None:
            return await limit_response(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


class TranscriptResponse(BaseModel):
    language: Language
    model: str
    text: str


def recognize(upload: UploadFile, language: Language, adapter: AsrAdapter, settings: Settings, slots: BoundedSemaphore):
    if not slots.acquire(blocking=False):
        return error(503, "asr_busy", "Локальное распознавание занято. Повторите запрос позже.")
    try:
        return recognize_file(upload, language, adapter, settings)
    finally:
        slots.release()


def recognize_file(upload: UploadFile, language: Language, adapter: AsrAdapter, settings: Settings):
    # No client filename is used as a filesystem path. The directory belongs only
    # to this request. Thread completion precedes deletion, also on cancellation.
    with TemporaryDirectory(prefix="audiomask-", dir=settings.temp_directory) as directory:
        path = Path(directory) / "input.wav"
        size = 0
        with path.open("wb") as target:
            while chunk := upload.file.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_file_bytes:
                    return error(413, "upload_too_large", "Превышен допустимый размер аудиофайла.")
                target.write(chunk)
        if not size:
            return error(422, "empty_audio", "Аудиофайл пуст.")
        try:
            prepared = prepare_wav(path, Path(directory) / "normalized.wav", settings)
        except InvalidAudio:
            return error(415, "invalid_audio", "Нужен корректный WAV PCM, mono или stereo, 8–192 кГц в пределах допустимой длительности.")
        except AudioPreparationUnavailable:
            return error(503, "audio_preparation_unavailable", "Преобразование WAV недоступно: зависимости не подключены.")
        try:
            text = adapter.transcribe(prepared, language)
        except AsrTimeout:
            return error(504, "asr_timeout", "Превышено время локального распознавания речи.")
        except AsrFfmpegUnavailable:
            return error(503, "ffmpeg_unavailable", "FFmpeg для GigaAM не настроен или недоступен. Укажите путь в конфигурации backend.")
        except AsrUnavailable:
            return error(503, "asr_unavailable", "Локальное распознавание речи пока не подключено или недоступно.")
        except Exception:
            return error(502, "asr_failed", "Не удалось выполнить локальное распознавание речи.")
        if not isinstance(text, str):
            return error(502, "asr_failed", "ASR вернул некорректный ответ.")
        return TranscriptResponse(language=language, model=MODELS[language], text=text)


def create_app(settings: Settings | None = None, adapters: Mapping[str, AsrAdapter] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    registry = {"gigaam-multi": GigaAMAdapter(settings.gigaam, settings), "whisper": WhisperAdapter(settings.whisper, settings)}
    slots = BoundedSemaphore(settings.max_concurrent_asr)
    if adapters is not None:
        registry.update(adapters)
    app = FastAPI(title="AudioMask local ASR", debug=False)
    quality_file_limit = max(settings.max_file_bytes, 44 + 32000 * settings.max_duration_seconds)
    app.add_middleware(BodyLimit, limit=settings.max_file_bytes + 64 * 1024,
                       masking_timeout=settings.masking_timeout_seconds,
                       quality_limit=settings.max_file_bytes + 2 * quality_file_limit + 64 * 1024,
                       quality_timeout=settings.quality_timeout_seconds)
    app.include_router(quality_router(settings, quality_file_limit))
    masking_executor = configured_masking_executor(settings)
    masking_slot = BoundedSemaphore(1)

    def masking_available(request: Request) -> bool:
        if masking_executor is None:
            return False
        if not masking_executor.test_mode:
            return True
        if request.client is None:
            return False
        try:
            return ip_address(request.client.host).is_loopback
        except ValueError:
            return False

    @app.get("/api/masking/status")
    def masking_status(request: Request):
        available = masking_available(request)
        test_mode = available and masking_executor is not None and masking_executor.test_mode
        return JSONResponse({"available": available, "test_mode": test_mode, "notice": NOTICE if test_mode else None},
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/masking/process")
    async def masking_process(request: Request):
        if masking_executor is None or not masking_available(request):
            return error(503, "masking_unavailable", "Маскирование недоступно.")
        if not masking_slot.acquire(blocking=False):
            return error(503, "masking_busy", "Обработка занята. Повторите запрос позже.")
        cancelled = Event()
        deadline = request.scope["audiomask.masking_deadline"]

        def checkpoint():
            if cancelled.is_set():
                raise MaskingCancelled()
            if monotonic() >= deadline:
                raise TimeoutError()

        async def watch_disconnect():
            while (await request.receive())["type"] != "http.disconnect":
                pass
            cancelled.set()

        try:
            async with request.form(max_files=1, max_fields=2, max_part_size=1024) as form:
                upload = form.get("file")
                mode, matrix = form.get("mode", "two-sided"), form.get("matrix", "64")
                if (not isinstance(upload, UploadFile) or set(form) - {"file", "mode", "matrix"}
                        or len(form.multi_items()) != len(form) or mode not in MODES
                        or matrix not in tuple(map(str, MATRICES))):
                    return error(422, "invalid_form", "Передайте один аудиофайл, допустимый режим и размер матрицы.")
                failure = None
                async with create_task_group() as task_group:
                    task_group.start_soon(watch_disconnect)
                    try:
                        result = await run_in_threadpool(process_upload, upload.file, mode, int(matrix),
                                                         masking_executor, settings, checkpoint)
                    except Exception as exc:
                        failure = exc
                    finally:
                        task_group.cancel_scope.cancel()
                checkpoint()
                if failure is not None:
                    raise failure
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except MaskingCancelled:
            return Response(status_code=499)
        except TimeoutError:
            return error(504, "masking_timeout", "Истекло время обработки.")
        except WorkerUnavailable:
            return error(503, "masking_unavailable", "Исполнитель маскирования недоступен.")
        except WorkerFailed:
            return error(502, "masking_failed", "Исполнитель маскирования не вернул корректный результат.")
        except HTTPException:
            return error(422, "invalid_form", "Некорректный multipart-запрос.")
        except UploadTooLarge:
            return error(413, "upload_too_large", "Превышен допустимый размер аудиофайла.")
        except EmptyUpload:
            return error(422, "empty_audio", "Аудиофайл пуст.")
        except InvalidAudio:
            return error(415, "invalid_audio", "Не удалось декодировать аудио. Проверьте формат, целостность и длительность записи.")
        except AudioPreparationUnavailable:
            return error(503, "audio_preparation_unavailable", "Преобразование аудио недоступно. Для этого файла нужен настроенный FFmpeg.")
        except Exception:
            return error(500, "masking_failed", "Не удалось выполнить обработку.")
        finally:
            cancelled.set()
            masking_slot.release()

    @app.get("/api/health")
    def health():
        # Liveness only: this does not claim that model inference is ready.
        return {"status": "ok"}

    @app.post("/api/asr/transcribe", response_model=TranscriptResponse,
              openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                  "type": "object", "required": ["file", "language"], "additionalProperties": False,
                  "properties": {"file": {"type": "string", "format": "binary"},
                                 "language": {"type": "string", "enum": ["ru", "en"]}}
              }}}}},
              responses={413: {"description": "Upload too large"}, 415: {"description": "Unsupported audio"},
                         422: {"description": "Invalid form"}, 503: {"description": "ASR unavailable"},
                         502: {"description": "ASR failed"}, 504: {"description": "ASR timeout"},
                         500: {"description": "Internal error"}})
    async def transcribe(request: Request):
        try:
            async with request.form(max_files=1, max_fields=2, max_part_size=1024) as form:
                if set(form) != {"file", "language"} or len(form.multi_items()) != 2:
                    return error(422, "invalid_form", "Передайте только один файл file и язык language: ru или en.")
                upload, language = form["file"], form["language"]
                if not isinstance(upload, UploadFile):
                    return error(422, "invalid_form", "Поле file должно содержать аудиофайл.")
                if language not in ("ru", "en"):
                    return error(422, "invalid_language", "Допустимые языки: ru и en.")
                return await run_in_threadpool(recognize, upload, language, registry[MODELS[language]], settings, slots)
        except HTTPException:
            return error(422, "invalid_form", "Некорректный multipart-запрос.")
        except Exception:
            return error(500, "internal_error", "Не удалось обработать запрос локального ASR.")

    return app


app = create_app()
