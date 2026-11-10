from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping
from threading import BoundedSemaphore

from fastapi import FastAPI, Request
from starlette.datastructures import UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .asr import AsrAdapter, AsrUnavailable, AsrTimeout, Language, MODELS, WhisperAdapter, GigaAMAdapter
from .audio import InvalidAudio, prepare_wav, AudioPreparationUnavailable
from .config import Settings


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class BodyLimit:
    """Bound multipart data before parsing/spooling, even without Content-Length."""
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/asr/transcribe":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.limit:
                return await error(413, "upload_too_large", "Превышен допустимый размер запроса.")(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
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
    app.add_middleware(BodyLimit, limit=settings.max_file_bytes + 64 * 1024)

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
