import asyncio
from base64 import b64decode
from dataclasses import replace
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
from httpx import Request

from app.config import Settings
from app.main import create_app
from app.masking import CopyMaskingStub, MATRICES, NOTICE
from test_api import wav

PROCESS = "/api/masking/process"
STATUS = "/api/masking/status"


class MaskingTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(temp_directory=self.root, masking_stub=True)
        self.client = self.client_for(create_app(self.settings))

    def client_for(self, app, address="127.0.0.1"):
        client = TestClient(app, client=(address, 12345))
        self.addCleanup(client.close)
        return client

    def post(self, audio, params=None, client=None):
        return (client or self.client).post(PROCESS, data=params, files={"file": ("sample.wav", audio)})

    def assert_clean(self):
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_local_development_gate(self):
        for env, enabled in [
            ({}, False), ({"AUDIOMASK_MASKING_STUB": "1"}, False),
            ({"AUDIOMASK_ENV": "production", "AUDIOMASK_MASKING_STUB": "1"}, False),
            ({"AUDIOMASK_ENV": "development"}, False),
            ({"AUDIOMASK_ENV": "development", "AUDIOMASK_MASKING_STUB": "1"}, True),
        ]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                settings = replace(Settings.from_env(), temp_directory=self.root)
                self.assertEqual(settings.masking_stub, enabled)
                client = self.client_for(create_app(settings))
                self.assertEqual(client.get(STATUS).json()["test_mode"], enabled)
                response = self.post(wav(), client=client)
                self.assertEqual(response.status_code, 200 if enabled else 503)
                if not enabled:
                    self.assertEqual(response.json()["error"]["code"], "masking_unavailable")
                    self.assertNotIn("masked", response.json())
        remote = self.client_for(create_app(self.settings), "192.0.2.1")
        self.assertFalse(remote.get(STATUS).json()["test_mode"])
        self.assertEqual(self.post(wav(), client=remote).status_code, 503)
        self.assert_clean()

    def test_default_parameters_wav_bytes_and_label(self):
        audio = wav(frames=160)[:-2] + b"\x19\x01"
        response = self.post(audio)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        result = response.json()
        self.assertIs(result["test_mode"], True)
        self.assertIs(result["masking_performed"], False)
        self.assertEqual(result["notice"], NOTICE)
        self.assertEqual(result["mode"], "two-sided")
        self.assertEqual((result["selected_matrix"], result["applied_matrix"]), (64, 16))
        for key in ("masked", "demasked"):
            output = result[key]
            self.assertEqual(output["media_type"], "audio/wav")
            self.assertEqual(output["file_name"], f"test-{key}.wav")
            self.assertEqual(b64decode(output["base64"], validate=True), audio)
        self.assert_clean()

    def test_files_are_independent_and_original_is_untouched(self):
        prepared, masked, demasked = (self.root / name for name in ("in.wav", "a.wav", "b.wav"))
        payload = wav()
        prepared.write_bytes(payload)
        self.assertEqual(CopyMaskingStub(self.settings).process(prepared, "one-sided", 4, masked, demasked, lambda: None), 4)
        self.assertFalse(masked.samefile(demasked))
        self.assertFalse(masked.samefile(prepared))
        masked.write_bytes(b"changed")
        self.assertEqual(demasked.read_bytes(), payload)
        self.assertEqual(prepared.read_bytes(), payload)

    def test_resampling_and_downmix(self):
        response = self.post(wav(rate=48000, channels=2, frames=192), {"mode": "one-sided", "matrix": "128"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["applied_matrix"], 8)
        for key in ("masked", "demasked"):
            with wave.open(BytesIO(b64decode(result[key]["base64"])), "rb") as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()),
                                 (16000, 1, 2, 64))
                self.assertEqual(audio.readframes(64), bytes(128))
        self.assert_clean()

    def test_matrix_boundaries_and_both_modes(self):
        for index, size in enumerate(MATRICES):
            first = 1 if index == 0 else MATRICES[index - 1] ** 2 + 1
            last = size ** 2 if index < len(MATRICES) - 1 else 300000
            for frames, mode in [(first, "one-sided"), (last, "two-sided")]:
                with self.subTest(frames=frames, mode=mode):
                    response = self.post(wav(frames=frames), {"mode": mode, "matrix": "512"})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()["applied_matrix"], size)
                    self.assertEqual(response.json()["mode"], mode)
        for size in MATRICES:
            response = self.post(wav(frames=65537), {"matrix": str(size)})
            self.assertEqual(response.json()["applied_matrix"], size)
        self.assert_clean()

    def test_invalid_files_fields_and_limits(self):
        for payload, params, status in [
            (b"", None, 422), (wav(frames=0), None, 415), (b"not wav", None, 503),
            (wav(), {"mode": "invalid"}, 422), (wav(), {"matrix": "5"}, 422),
            (wav(), {"matrix": ["4", "8"]}, 422), (wav(), {"other": "value"}, 422),
        ]:
            with self.subTest(params=params, status=status):
                response = self.post(payload, params)
                self.assertEqual(response.status_code, status, response.text)
                self.assertNotIn("masked", response.json())
        client = self.client_for(create_app(replace(self.settings, max_file_bytes=64)))
        self.assertEqual(self.post(wav(), client=client).status_code, 413)
        self.assertEqual(client.post(PROCESS, content=b"x" * 66000).status_code, 413)
        self.assert_clean()

    def test_partial_failure_and_timeout_discard_outputs(self):
        def fail(_stub, prepared, mode, matrix, masked, demasked, checkpoint):
            masked.write_bytes(prepared.read_bytes())
            raise OSError("private path")

        with patch.object(CopyMaskingStub, "process", fail):
            response = self.post(wav())
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private path", response.text)
        self.assertNotIn("masked", response.json())
        self.assert_clean()

        def stall(_stub, prepared, mode, matrix, masked, demasked, checkpoint):
            masked.write_bytes(prepared.read_bytes())
            time.sleep(0.07)
            checkpoint()

        client = self.client_for(create_app(replace(self.settings, masking_timeout_seconds=0.05)))
        with patch.object(CopyMaskingStub, "process", stall):
            response = self.post(wav(), client=client)
        self.assertEqual(response.status_code, 504, response.text)
        self.assertEqual(response.json()["error"]["code"], "masking_timeout")
        self.assert_clean()
        self.assertEqual(self.post(wav()).status_code, 200)

    def test_disconnect_during_processing_cleans_partial_output(self):
        started = Event()

        def wait_for_disconnect(_stub, prepared, mode, matrix, masked, demasked, checkpoint):
            masked.write_bytes(prepared.read_bytes())
            started.set()
            while True:
                checkpoint()
                time.sleep(0.005)

        async def disconnect():
            request = Request("POST", "http://localhost" + PROCESS, files={"file": ("sample.wav", wav())})
            payload = request.read()
            received = False
            sent = []

            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {"type": "http.request", "body": payload}
                for _ in range(200):
                    if started.is_set():
                        return {"type": "http.disconnect"}
                    await asyncio.sleep(0.005)
                raise AssertionError("Processing did not start")

            async def send(message):
                sent.append(message)

            app = create_app(replace(self.settings, masking_timeout_seconds=2))
            await app({"type": "http", "path": PROCESS, "method": "POST", "query_string": b"",
                       "headers": [(name.lower(), value) for name, value in request.headers.raw],
                       "client": ("127.0.0.1", 12345)}, receive, send)
            self.assertEqual(sent[0]["status"], 499)

        with patch.object(CopyMaskingStub, "process", wait_for_disconnect):
            asyncio.run(disconnect())
        self.assert_clean()
