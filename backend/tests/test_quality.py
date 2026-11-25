import asyncio
from dataclasses import replace
from pathlib import Path
from shutil import copyfile
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import Request

from app.config import Settings
from app.main import create_app
from test_api import wav


STATUS = "/api/quality/status"
EVALUATE = "/api/quality/evaluate"
TEST_PAIRS = {"pairs": ["masked", "demasked"]}
ALL_PAIRS = {"pairs": ["masked", "demasked", "masked_demasked"]}


class QualityTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="audiomask quality tests ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.settings = Settings(temp_directory=self.uploads, quality_python=Path(sys.executable))
        self.audio = wav(frames=16000)
        self.files = {name: ("audio.wav", self.audio) for name in ("original", "masked", "demasked")}

    def launch(self, scenario="normal", **settings):
        script = self.root / f"{scenario}.py"
        copyfile(Path(__file__).with_name("fake_quality_worker.py"), script)
        patcher = patch("app.quality.SCRIPT", script)
        patcher.start()
        self.addCleanup(patcher.stop)
        return create_app(replace(self.settings, **settings))

    def assert_clean(self):
        self.assertEqual(list(self.uploads.iterdir()), [])

    def set_padding_inputs(self, *, original=60640, masked=65536, demasked=66000):
        header = wav(frames=original)[:-2 * original]
        pcm = (b"\x34\x12\xcc\xed" * original)[:2 * original]
        self.files = {
            "original": ("source.wav", header + pcm),
            "masked": ("masked.wav", wav(frames=masked)),
            "demasked": ("demasked.wav", wav(frames=demasked)),
        }

    def test_pads_from_the_same_original_independently_for_all_selected_pairs(self):
        self.set_padding_inputs()
        with TestClient(self.launch("padding")) as client:
            response = client.post(EVALUATE, data=ALL_PAIRS, files=self.files)
        self.assertEqual(response.status_code, 200, response.text)
        comparisons = response.json()["comparisons"]
        for pair, expected in (("masked", 2), ("demasked", 3)):
            self.assertEqual(comparisons[pair], {
                metric: {"status": "success", "value": expected + offset}
                for metric, offset in (("PESQ", 0), ("ViSQOL", 0.1), ("ViSQOL_LATTICE", 0.2))
            })
        self.assertTrue(all(item["status"] == "error" and "различаются" in item["message"]
                            for item in comparisons["masked_demasked"].values()))
        self.assert_clean()

    def test_padding_does_not_bypass_original_minimum_frames(self):
        with TestClient(self.launch("padding")) as client:
            for original in (3999, 15999):
                with self.subTest(original=original):
                    self.set_padding_inputs(original=original)
                    response = client.post(EVALUATE, data={"pairs": "masked"},
                                           files={name: self.files[name] for name in ("original", "masked")})
                    self.assertEqual(response.status_code, 200, response.text)
                    scores = response.json()["comparisons"]["masked"]
                    for metric in ("ViSQOL", "ViSQOL_LATTICE"):
                        self.assertIn("слишком короткая", scores[metric]["message"])
                    if original < 4000:
                        self.assertIn("слишком короткая", scores["PESQ"]["message"])
                    else:
                        self.assertEqual(scores["PESQ"]["status"], "success")
                    self.assert_clean()

    def test_padding_preserves_upload_size_and_duration_limits(self):
        self.set_padding_inputs()
        files = {name: self.files[name] for name in ("original", "masked")}
        for settings, status in (({"max_file_bytes": 100000}, 413),
                                 ({"max_duration_seconds": 4, "max_file_bytes": 125000}, 413),
                                 ({"max_duration_seconds": 4, "max_file_bytes": 200000}, 415)):
            with self.subTest(status=status), TestClient(create_app(replace(self.settings, **settings))) as client:
                response = client.post(EVALUATE, data={"pairs": "masked"}, files=files)
                self.assertEqual(response.status_code, status, response.text)
            self.assert_clean()

    def test_each_pair_alone_and_all_pairs_use_ordered_recordings(self):
        pairs = {"masked": ("original", "masked"),
                 "demasked": ("original", "demasked"),
                 "masked_demasked": ("masked", "demasked")}
        with TestClient(self.launch("ordered")) as client:
            for selected in ([pair] for pair in pairs):
                with self.subTest(selected=selected):
                    files = {name: self.files[name] for name in pairs[selected[0]]}
                    response = client.post(EVALUATE, data={"pairs": selected}, files=files)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(list(response.json()["comparisons"]), selected)
            response = client.post(EVALUATE, data={"pairs": list(pairs)}, files=self.files)
            self.assertEqual(response.status_code, 200, response.text)
            comparisons = response.json()["comparisons"]
            self.assertEqual(list(comparisons), list(pairs))
            for name, expected in zip(pairs, (2, 3, 4)):
                self.assertEqual(comparisons[name], {
                    metric: {"status": "success", "value": value} for metric, value in
                    (("PESQ", expected), ("ViSQOL", expected + 0.1), ("ViSQOL_LATTICE", expected + 0.2))
                })
        self.assert_clean()

    def test_availability_and_independent_results_after_normalization(self):
        with TestClient(self.launch()) as client:
            reply = client.get(STATUS).json()["metrics"]
            self.assertEqual(reply["PESQ"]["status"], "available")
            self.assertEqual(reply["ViSQOL"]["status"], "unavailable")
            self.files["original"] = ("source.wav", wav(rate=48000, channels=2, frames=48000))
            response = client.post(EVALUATE, data=TEST_PAIRS, files=self.files)
        self.assertEqual(response.status_code, 200, response.text)
        scores = response.json()["comparisons"]
        self.assertEqual(scores["masked"]["PESQ"], {"status": "success", "value": 4.321})
        self.assertEqual(scores["masked"]["ViSQOL"]["status"], "unavailable")
        self.assertEqual(scores["masked"]["ViSQOL_LATTICE"], {"status": "success", "value": 4.2})
        self.assertEqual(scores["demasked"]["PESQ"]["status"], "error")
        self.assertEqual(scores["demasked"]["ViSQOL"], {"status": "success", "value": 3.2})
        self.assertEqual(scores["demasked"]["ViSQOL_LATTICE"]["status"], "unavailable")
        self.assert_clean()

    def test_unconfigured_metrics_and_input_validation(self):
        with TestClient(create_app(replace(self.settings, quality_python=None))) as client:
            statuses = client.get(STATUS).json()["metrics"]
            self.assertEqual({item["status"] for item in statuses.values()}, {"unavailable"})
            scores = client.post(EVALUATE, data=TEST_PAIRS, files=self.files).json()["comparisons"]
            self.assertEqual(scores["masked"]["PESQ"]["status"], "unavailable")
            for data in ({}, {"pairs": ["unknown"]}, {"pairs": ["masked", "masked"]}):
                self.assertEqual(client.post(EVALUATE, data=data, files=self.files).json()["error"]["code"], "invalid_pairs")
            self.assertEqual(client.post(EVALUATE, data=TEST_PAIRS, files={"original": self.files["original"]}).status_code, 422)
            self.assertEqual(client.post(EVALUATE, data=TEST_PAIRS, files=dict(self.files, masked=("empty.wav", b""))).status_code, 422)
            self.assertEqual(client.post(EVALUATE, data=TEST_PAIRS, files=dict(self.files, masked=("bad.wav", b"bad"))).status_code, 415)
        self.assert_clean()

    def test_duration_mismatch_is_rejected_without_changing_other_pair(self):
        with TestClient(self.launch()) as client:
            self.files["masked"] = ("short.wav", wav(frames=15999))
            scores = client.post(EVALUATE, data=TEST_PAIRS, files=self.files).json()["comparisons"]
        self.assertTrue(all(item["status"] == "error" for item in scores["masked"].values()))
        self.assertEqual(scores["demasked"]["ViSQOL"]["status"], "success")
        self.assert_clean()

    def test_worker_timeout_preserves_other_metric(self):
        self.set_padding_inputs()
        with TestClient(self.launch("slow", quality_timeout_seconds=1)) as client:
            scores = client.post(EVALUATE, data=TEST_PAIRS, files=self.files).json()["comparisons"]
        self.assertIn("Истекло время", scores["masked"]["PESQ"]["message"])
        self.assertEqual(scores["demasked"]["ViSQOL"]["status"], "success")
        self.assert_clean()

    def test_worker_failure_preserves_other_metric_and_hides_stderr(self):
        self.set_padding_inputs()
        with TestClient(self.launch("crash")) as client:
            response = client.post(EVALUATE, data=TEST_PAIRS, files=self.files)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private worker detail", response.text)
        scores = response.json()["comparisons"]
        self.assertEqual(scores["demasked"]["PESQ"]["status"], "error")
        self.assertEqual(scores["demasked"]["ViSQOL"]["status"], "success")
        self.assert_clean()

    def test_disconnect_cancels_process_and_cleans_uploads(self):
        self.set_padding_inputs()
        app = self.launch("slow", quality_timeout_seconds=10)
        request = Request("POST", "http://localhost" + EVALUATE, data=TEST_PAIRS, files=self.files)
        payload = request.read()
        sent = []
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload}
            while not (self.root / "started").is_file():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "path": EVALUATE, "method": "POST", "query_string": b"",
                 "headers": [(name.lower(), value) for name, value in request.headers.raw]}
        asyncio.run(asyncio.wait_for(app(scope, receive, send), timeout=5))
        self.assertEqual(sent[0]["status"], 499)
        self.assert_clean()
