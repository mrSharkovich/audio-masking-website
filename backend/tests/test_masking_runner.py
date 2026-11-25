import asyncio
from base64 import b64decode
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
from dataclasses import replace
from io import BytesIO
import os
from pathlib import Path
from shutil import copyfile
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
from httpx import Request

from app.config import Settings
from app.main import create_app
from test_masking import PROCESS, STATUS
from test_api import wav


class MaskingRunnerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="audiomask runner tests ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.settings = Settings(temp_directory=self.uploads, masking_runner_python=Path(sys.executable))

    def configured(self, scenario):
        script = self.root / f"{scenario}.py"
        copyfile(Path(__file__).with_name("fake_masking_runner.py"), script)
        return replace(self.settings, masking_runner_script=script)

    def client(self, settings):
        client = TestClient(create_app(settings), client=("127.0.0.1", 10000))
        self.addCleanup(client.close)
        return client

    def post(self, client, audio=None):
        return client.post(PROCESS, files={"file": ("recording.wav", audio if audio is not None else wav())},
                           data={"mode": "one-sided", "matrix": "16"})

    def assert_clean(self):
        self.assertEqual(list(self.uploads.iterdir()), [])

    def assert_child_stopped(self):
        pid = int((self.root / "child.pid").read_text())
        if os.name != "nt":
            return  # Windows Job Object is verified on the supported deployment platform.
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x00100000, False, pid)
        if handle:
            try:
                self.assertEqual(api.WaitForSingleObject(handle, 2000), 0)
            finally:
                api.CloseHandle(handle)
        else:
            self.assertEqual(ctypes.get_last_error(), 87)  # No such process.

    def test_runs_configured_script_and_returns_both_wavs_and_runner_matrix(self):
        with patch.dict(os.environ, {"AUDIOMASK_MASKING_RUNNER_PYTHON": sys.executable,
                                    "AUDIOMASK_MASKING_RUNNER_SCRIPT": str(self.configured("success").masking_runner_script)},
                        clear=True):
            settings = replace(Settings.from_env(), temp_directory=self.uploads)
        client = self.client(settings)
        self.assertEqual(client.get(STATUS).json(), {"available": True, "test_mode": False, "notice": None})
        response = self.post(client, wav(rate=48000, channels=2, frames=4800))
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertIs(result["test_mode"], False)
        self.assertIs(result["masking_performed"], True)
        self.assertEqual((result["selected_matrix"], result["applied_matrix"]), (16, 4))
        self.assertEqual(result["mode"], "one-sided")
        for key in ("masked", "demasked"):
            self.assertEqual(result[key]["file_name"], f"{key}.wav")
            with wave.open(BytesIO(b64decode(result[key]["base64"], validate=True)), "rb") as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()),
                                 (16000, 1, 2, 1600))
        self.assert_clean()

    def test_rejects_incomplete_invalid_and_failed_outputs(self):
        for scenario in ("missing", "invalid_wav", "bad_json", "bad_matrix", "failure"):
            with self.subTest(scenario=scenario):
                response = self.post(self.client(self.configured(scenario)))
                self.assertEqual(response.status_code, 502, response.text)
                self.assertEqual(response.json()["error"]["code"], "masking_failed")
                self.assertNotIn("private runner data", response.text)
                self.assertNotIn(str(self.root), response.text)
                self.assertNotIn("masked", response.json())
                self.assert_clean()

    def test_launch_error_is_sanitized(self):
        client = self.client(self.configured("success"))
        with patch("app.process.subprocess.Popen", side_effect=OSError("private launch path")):
            response = self.post(client)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "masking_unavailable")
        self.assertNotIn("private launch path", response.text)
        self.assert_clean()

    def test_partial_invalid_and_conflicting_configuration_is_disabled(self):
        configured = self.configured("success")
        for settings in (Settings(), self.settings, replace(configured, masking_runner_script=Path("relative.py")),
                         replace(configured, masking_runner_script=self.root / "missing.py"),
                         replace(configured, masking_stub=True)):
            with self.subTest(settings=settings):
                client = self.client(settings)
                self.assertFalse(client.get(STATUS).json()["available"])
                self.assertEqual(self.post(client).json()["error"]["code"], "masking_unavailable")
        stub = self.client(Settings(temp_directory=self.uploads, masking_stub=True))
        result = self.post(stub).json()
        self.assertIs(result["test_mode"], True)
        self.assertIs(result["masking_performed"], False)
        self.assert_clean()

    def test_timeout_and_parallel_limit(self):
        settings = replace(self.configured("wait"), masking_timeout_seconds=2)
        client = self.client(settings)
        with ThreadPoolExecutor(max_workers=1) as pool:
            active = pool.submit(self.post, client)
            until = time.monotonic() + 1.5
            while not (self.root / "started").exists() and time.monotonic() < until:
                time.sleep(0.01)
            self.assertTrue((self.root / "started").exists())
            response = self.post(client)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "masking_busy")
            self.assertEqual(active.result(timeout=8).status_code, 504)
        self.assert_child_stopped()
        self.assert_clean()

    def test_disconnect_reaps_process_tree_and_cleans_work_directory(self):
        app = create_app(replace(self.configured("wait"), masking_timeout_seconds=5))

        async def disconnect():
            request = Request("POST", "http://localhost" + PROCESS, files={"file": ("sample.wav", wav())},
                              data={"mode": "one-sided", "matrix": "16"})
            payload = request.read()
            sent = []
            received = False

            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {"type": "http.request", "body": payload}
                while not (self.root / "started").exists():
                    await asyncio.sleep(0.01)
                return {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            await app({"type": "http", "path": PROCESS, "method": "POST", "query_string": b"",
                       "headers": [(name.lower(), value) for name, value in request.headers.raw],
                       "client": ("127.0.0.1", 12345)}, receive, send)
            self.assertEqual(sent[0]["status"], 499)

        asyncio.run(disconnect())
        self.assert_child_stopped()
        self.assert_clean()
