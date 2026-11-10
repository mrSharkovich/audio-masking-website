from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
from dataclasses import replace
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient

from app.asr import AsrUnavailable, GigaAMAdapter, WhisperAdapter
from app.config import ModelRuntime, Settings
from app.main import create_app
from test_api import wav


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="asr test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.weights = self.root / "local weights"
        self.weights.mkdir()
        self.mode = self.weights / "mode"
        self.mode.write_text("success")
        self.settings = Settings(temp_directory=self.uploads, worker_timeout_seconds=2)
        runtime = ModelRuntime(Path(sys.executable), self.weights)
        script = Path(__file__).parent.resolve() / "fake_worker.py"
        self.adapters = {"gigaam-multi": GigaAMAdapter(runtime, self.settings, worker=script),
                         "whisper": WhisperAdapter(runtime, self.settings, worker=script)}
        self.client = TestClient(create_app(self.settings, self.adapters))
        self.addCleanup(self.client.close)

    def post(self, language="ru", payload=None, client=None):
        return (client or self.client).post("/api/asr/transcribe", data={"language": language},
                                            files={"file": ("../../source.wav", payload or wav())})

    def assertClean(self):
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_real_subprocess_routing_and_conversion(self):
        for language, model in [("ru", "gigaam-multi"), ("en", "whisper")]:
            response = self.post(language, wav(rate=48000, channels=2, frames=4800))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"language": language, "model": model, "text": "test-only:" + language})
            self.assertClean()

    def test_worker_failure_protocol_and_output_limits(self):
        for mode, status in [("unavailable", 503), ("failure", 502), ("invalid", 502),
                             ("schema", 502), ("flood", 502), ("stderr_flood", 502)]:
            with self.subTest(mode=mode):
                self.mode.write_text(mode)
                response = self.post(payload=wav(rate=48000, channels=2, frames=4800))
                self.assertEqual(response.status_code, status, response.text)
                self.assertNotIn("private", response.text)
                self.assertNotIn(str(self.root), response.text)
                self.assertClean()
        self.mode.write_text("success")
        self.assertEqual(self.post().status_code, 200)  # Slot released on errors.

    def test_timeout_and_slot_release(self):
        self.mode.write_text("timeout")
        started = time.monotonic()
        response = self.post()
        self.assertEqual(response.status_code, 504, response.text)
        self.assertEqual(response.json()["error"]["code"], "asr_timeout")
        self.assertLess(time.monotonic() - started, 8)
        self.assertClean()
        self.mode.write_text("success")
        self.assertEqual(self.post().status_code, 200)

    def test_concurrent_languages_share_one_limit(self):
        self.mode.write_text("timeout")
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(self.post)
            deadline = time.monotonic() + 1.5
            while not (self.weights / "ready").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.weights / "ready").is_file())
            response = self.post("en")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "asr_busy")
            self.assertEqual(first.result(timeout=8).status_code, 504)
        self.assertClean()

    def test_missing_interpreter_weights_and_wrong_language(self):
        for runtime in [ModelRuntime(), ModelRuntime(self.root / "missing.exe", self.weights),
                        ModelRuntime(Path(sys.executable), self.root / "missing weights"),
                        ModelRuntime(Path("relative/python.exe"), self.weights)]:
            with TestClient(create_app(replace(self.settings, gigaam=runtime))) as client:
                self.assertEqual(self.post(client=client).status_code, 503)
        with self.assertRaises(AsrUnavailable):
            self.adapters["whisper"].transcribe(self.root / "a.wav", "ru")
        self.assertClean()

    @unittest.skipUnless(os.name == "nt", "Windows Job Object integration")
    def test_windows_job_kills_descendants_on_timeout_and_normal_exit(self):
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        for mode, status in [("tree_timeout", 504), ("tree_success", 200)]:
            self.mode.write_text(mode)
            response = self.post()
            self.assertEqual(response.status_code, status, response.text)
            pid = int((self.weights / "child.pid").read_text())
            handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if handle:
                try:
                    self.assertEqual(api.WaitForSingleObject(handle, 2000), 0)
                finally:
                    api.CloseHandle(handle)
            self.assertClean()


if __name__ == "__main__":
    unittest.main()
