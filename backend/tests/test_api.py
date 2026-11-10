import asyncio
from dataclasses import replace
import io
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient

from app.asr import AsrUnavailable
from app.config import Settings
from app.main import create_app


def wav(*, rate=16000, channels=1, width=2, frames=160) -> bytes:
    # Synthetic silence is generated in memory; no user recordings or datasets.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes(bytes(frames * channels * width))
    return buffer.getvalue()


class RecordingAdapter:
    def __init__(self, failure=None, text="test adapter text"):
        self.calls = []
        self.failure, self.text = failure, text

    def transcribe(self, audio, language):
        assert audio.is_file()
        self.calls.append((audio, language, audio.read_bytes()))
        if self.failure:
            raise self.failure
        return self.text


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(temp_directory=self.root)
        self.ru, self.en = RecordingAdapter(), RecordingAdapter()
        self.client = TestClient(create_app(self.settings, {"gigaam-multi": self.ru, "whisper": self.en}))
        self.addCleanup(self.client.close)

    def post(self, payload=None, language="ru", name="input.wav", client=None):
        return (client or self.client).post("/api/asr/transcribe", data={"language": language},
                                            files={"file": (name, wav() if payload is None else payload, "audio/wav")})

    def assertClean(self):
        self.assertEqual(list(self.root.iterdir()), [])

    def test_health_is_liveness_not_model_readiness(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_openapi_describes_multipart_contract(self):
        schema = self.client.get("/openapi.json").json()
        form = schema["paths"]["/api/asr/transcribe"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
        self.assertEqual(set(form["required"]), {"file", "language"})
        self.assertEqual(form["properties"]["language"]["enum"], ["ru", "en"])
        self.assertFalse(form["additionalProperties"])

    def test_routing_and_cleanup_for_both_languages(self):
        for language, model, adapter in [("ru", "gigaam-multi", self.ru), ("en", "whisper", self.en)]:
            with self.subTest(language=language):
                response = self.post(language=language, name="../../untrusted.wav")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"language": language, "model": model, "text": "test adapter text"})
                path, received_language, data = adapter.calls[-1]
                self.assertEqual(path.name, "input.wav")
                self.assertEqual(received_language, language)
                self.assertEqual(data, wav())
                self.assertFalse(path.exists())
                self.assertClean()
        self.assertEqual(len(self.ru.calls), 1)
        self.assertEqual(len(self.en.calls), 1)

    def test_model_from_client_is_rejected(self):
        response = self.client.post("/api/asr/transcribe", data={"language": "ru", "model": "whisper"},
                                    files={"file": ("a.wav", wav())})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.ru.calls + self.en.calls, [])

    def test_invalid_or_missing_fields(self):
        for language in ["de", "RU", "", "../../python"]:
            self.assertEqual(self.post(language=language).status_code, 422)
        self.assertEqual(self.client.post("/api/asr/transcribe", data={"language": "ru"}).status_code, 422)
        self.assertEqual(self.client.post("/api/asr/transcribe", files={"file": ("a.wav", wav())}).status_code, 422)
        self.assertEqual(self.client.post("/api/asr/transcribe", json={"language": "ru", "file": "a"}).status_code, 422)
        self.assertEqual(self.ru.calls + self.en.calls, [])

    def test_duplicate_fields_and_multiple_files(self):
        files = [("file", ("a.wav", wav())), ("file", ("b.wav", wav()))]
        self.assertEqual(self.client.post("/api/asr/transcribe", data={"language": "ru"}, files=files).status_code, 422)
        fields = [("file", ("a.wav", wav())), ("language", (None, "ru")), ("language", (None, "en"))]
        self.assertEqual(self.client.post("/api/asr/transcribe", files=fields).status_code, 422)
        self.assertClean()

    def test_content_validation_and_cleanup(self):
        broken = bytearray(wav()[:-2])
        # Correct outer length, but the data chunk still declares missing samples.
        struct.pack_into("<I", broken, 4, len(broken) - 8)
        odd = bytearray(wav() + b"x")
        struct.pack_into("<I", odd, 4, len(odd) - 8)
        struct.pack_into("<I", odd, 40, len(odd) - 44)
        for payload in [b"", b"not audio", b"ID3 fake mp3", wav()[:20], bytes(broken),
                        bytes(odd), wav(rate=4000), wav(channels=3), wav(frames=0)]:
            with self.subTest(size=len(payload)):
                response = self.post(payload)
                self.assertIn(response.status_code, [415, 422])
                self.assertClean()
        self.assertEqual(self.ru.calls + self.en.calls, [])

    def test_storage_errors_are_sanitized(self):
        with patch("app.main.TemporaryDirectory", side_effect=OSError("private storage path")):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private", response.text)
        self.assertEqual(self.ru.calls, [])
        self.assertClean()

    def test_content_not_extension_or_mime_decides_format(self):
        response = self.client.post("/api/asr/transcribe", data={"language": "en"},
                                    files={"file": ("unknown.bin", wav(), "application/octet-stream")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.post(b"not wav", name="valid.wav").status_code, 415)

    def test_file_limit_and_exact_boundary(self):
        with TestClient(create_app(replace(self.settings, max_file_bytes=len(wav())), {"gigaam-multi": self.ru})) as client:
            self.assertEqual(self.post(client=client).status_code, 200)
            self.assertEqual(self.post(wav() + b"x", client=client).status_code, 413)
        self.assertClean()

    def test_duration_limit(self):
        with TestClient(create_app(replace(self.settings, max_duration_seconds=1))) as client:
            self.assertEqual(self.post(wav(frames=16001), client=client).status_code, 415)
        self.assertClean()

    def test_total_body_limit_with_and_without_content_length(self):
        app = create_app(replace(self.settings, max_file_bytes=64))
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/asr/transcribe", content=b"x" * 66000).status_code, 413)

        async def chunked_request():
            messages = iter([{"type": "http.request", "body": b"x" * 40000, "more_body": True},
                             {"type": "http.request", "body": b"x" * 40000, "more_body": False}])
            sent = []
            async def receive():
                return next(messages)
            async def send(message):
                sent.append(message)
            await app({"type": "http", "path": "/api/asr/transcribe", "method": "POST", "headers": []}, receive, send)
            self.assertEqual(sent[0]["status"], 413)
        asyncio.run(chunked_request())
        self.assertClean()

    def test_default_adapters_are_unavailable(self):
        with TestClient(create_app(self.settings)) as client:
            for language in ["ru", "en"]:
                response = self.post(language=language, client=client)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "asr_unavailable")
                self.assertNotIn("text", response.json())
                self.assertClean()

    def test_adapter_errors_do_not_leak_paths_and_always_cleanup(self):
        for exception, status in [(AsrUnavailable("private path"), 503), (RuntimeError("secret/private/path"), 502)]:
            adapter = RecordingAdapter(failure=exception)
            with TestClient(create_app(self.settings, {"gigaam-multi": adapter})) as client:
                response = self.post(client=client)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private", response.text)
                self.assertFalse(adapter.calls[0][0].exists())
                self.assertClean()

    def test_empty_transcript_is_not_fabricated_and_invalid_response_is_rejected(self):
        for text, status in [("", 200), (None, 502)]:
            with TestClient(create_app(self.settings, {"gigaam-multi": RecordingAdapter(text=text)})) as client:
                response = self.post(client=client)
                self.assertEqual(response.status_code, status)
                if status == 200:
                    self.assertEqual(response.json()["text"], "")
                self.assertClean()

    def test_runtime_configuration_is_local_and_does_not_enable_inference(self):
        with patch.dict(os.environ, {"AUDIOMASK_GIGAAM_PYTHON": "vm-gigaam/python.exe",
                                     "AUDIOMASK_WHISPER_WEIGHTS": "vm-whisper/weights"}):
            settings = Settings.from_env()
        self.assertEqual(settings.gigaam.python, Path("vm-gigaam/python.exe"))
        self.assertEqual(settings.whisper.weights, Path("vm-whisper/weights"))
        with TestClient(create_app(settings)) as client:
            self.assertEqual(self.post(client=client).status_code, 503)


if __name__ == "__main__":
    unittest.main()
