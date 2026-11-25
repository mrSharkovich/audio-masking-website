from base64 import b64decode
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.process import WorkerTimeout, WorkerUnavailable, run_worker_process
from test_api import wav
from test_masking import PROCESS


class MaskingAudioTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uploads = self.root / "uploads"
        self.uploads.mkdir()
        self.ffmpeg = self.root / "ffmpeg fixture.exe"
        self.ffmpeg.touch()
        self.settings = Settings(temp_directory=self.uploads, masking_stub=True, ffmpeg_path=self.ffmpeg)
        self.client = self.create_client(self.settings)

    def create_client(self, settings):
        client = TestClient(create_app(settings), client=("127.0.0.1", 12345))
        self.addCleanup(client.close)
        return client

    def post(self, payload, name="untrusted.name", client=None, params=None):
        return (client or self.client).post(PROCESS, files={"file": (name, payload, "application/octet-stream")},
                                            data=params)

    def fake_decode(self, expected_payload, output, *, use_process=False):
        def convert(command, cwd, request, *, timeout, output_limit, checkpoint):
            self.assertEqual(command[0], str(self.ffmpeg))
            self.assertIsNone(request)
            self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
            formats = command[command.index("-format_whitelist") + 1].split(",")
            self.assertTrue({"wav", "mp3", "mov", "flac", "ogg", "aac"} <= set(formats))
            self.assertTrue({"concat", "hls", "dash"}.isdisjoint(formats))
            self.assertIn("-xerror", command)
            self.assertEqual(command[command.index("-map") + 1], "0:a:0")
            self.assertEqual(command[command.index("-t") + 1], "301")
            self.assertEqual(command[-9:-1], ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"])
            source, target = Path(command[command.index("-i") + 1]), Path(command[-1])
            self.assertEqual(source.read_bytes(), expected_payload)
            self.assertEqual(source.parent, cwd)
            self.assertNotEqual(source, target)
            if use_process:
                # Exercise the real bounded process transport without requiring FFmpeg.
                code = ("import sys; from pathlib import Path; assert not sys.stdin.read(); "
                        "Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))")
                result = run_worker_process([sys.executable, "-I", "-c", code, str(target), output.hex()],
                                            cwd, None, timeout=timeout, output_limit=output_limit, checkpoint=checkpoint)
            else:
                target.write_bytes(output)
                result = (0, b"")
            self.assertEqual(source.read_bytes(), expected_payload)
            return result
        return convert

    def test_compressed_uploads_are_probed_then_stub_receives_normalized_wav(self):
        # Signatures exercise the upload/decode dispatch. Decoding itself is simulated.
        for name, signature in {
            "song.mp3": b"ID3", "voice.m4a": b"\x00\x00\x00\x18ftypM4A ",
            "music.flac": b"fLaC", "capture.ogg": b"OggS", "clip.aac": b"\xff\xf1",
            "audio.webm": b"\x1a\x45\xdf\xa3",
        }.items():
            with self.subTest(name=name):
                payload, normalized = signature + b"test-only", wav(frames=64)
                with patch("app.masking_audio.run_worker_process", side_effect=self.fake_decode(payload, normalized)):
                    result = self.post(payload, name).json()
                self.assertEqual(result["applied_matrix"], 8)
                self.assertIs(result["test_mode"], True)
                for key in ("masked", "demasked"):
                    self.assertEqual(b64decode(result[key]["base64"]), normalized)
                self.assertEqual(list(self.uploads.iterdir()), [])

    def test_external_runner_receives_prepared_wav_after_non_pcm_upload(self):
        # The repository fixture checks the input format and both output paths.
        fixture = Path(__file__).with_name("fake_masking_runner.py").resolve()
        settings = replace(self.settings, masking_stub=False, masking_runner_python=Path(sys.executable),
                           masking_runner_script=fixture)
        payload = b"ID3test-only"
        with patch("app.masking_audio.run_worker_process", side_effect=self.fake_decode(payload, wav(), use_process=True)):
            response = self.post(payload, client=self.create_client(settings),
                                 params={"mode": "one-sided", "matrix": "16"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["applied_matrix"], 4)
        self.assertIs(result["masking_performed"], True)
        for key in ("masked", "demasked"):
            with wave.open(BytesIO(b64decode(result[key]["base64"])), "rb") as audio:
                self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()),
                                 (16000, 1, 2, 160))
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_decoder_failure_bad_output_and_timeout_produce_no_result(self):
        payload = b"corrupt file"
        scenarios = [
            ({"return_value": (1, b"private path")}, 415, "invalid_audio"),
            ({"return_value": (0, b"")}, 415, "invalid_audio"),
            ({"side_effect": self.fake_decode(payload, wav(frames=0))}, 415, "invalid_audio"),
            ({"side_effect": self.fake_decode(payload, wav(rate=8000))}, 415, "invalid_audio"),
            ({"side_effect": self.fake_decode(payload, wav(frames=4800001))}, 415, "invalid_audio"),
            ({"side_effect": WorkerUnavailable()}, 503, "audio_preparation_unavailable"),
            ({"side_effect": WorkerTimeout()}, 504, "masking_timeout"),
        ]
        for mock, status, code in scenarios:
            with self.subTest(status=status, code=code), patch("app.masking_audio.run_worker_process", **mock):
                response = self.post(payload)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json()["error"]["code"], code)
                self.assertNotIn("private path", response.text)
                self.assertNotIn("masked", response.json())
                self.assertEqual(list(self.uploads.iterdir()), [])

    def test_standard_wav_depends_on_contents_not_extension_or_ffmpeg(self):
        payload = wav(rate=48000, channels=2, frames=480)
        with patch("app.masking_audio.run_worker_process") as decoder:
            response = self.post(payload, "actually-wav.ogg")
        decoder.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        with wave.open(BytesIO(b64decode(response.json()["masked"]["base64"])), "rb") as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()),
                             (16000, 1, 2, 160))
