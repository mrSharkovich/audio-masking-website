import asyncio
from base64 import b64decode
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import sleep
import unittest
from unittest.mock import patch
import wave

from fastapi.testclient import TestClient
from httpx import Request

from app.config import Settings
from app.main import create_app
from app.process import WorkerTimeout, WorkerUnavailable, run_worker_process
from test_api import RecordingAdapter, wav
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

    def post(self, payload, name="untrusted.name", client=None, params=None, mime="application/octet-stream"):
        return (client or self.client).post(PROCESS, files={"file": (name, payload, mime)},
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

    def test_invalid_content_and_missing_audio_track_are_rejected_regardless_of_metadata(self):
        pdf = b"%PDF-1.7\n%%EOF\n"
        cases = [
            ("document.pdf", "application/pdf", pdf),
            ("document.wav", "audio/wav", pdf),
            ("document.mp3", "audio/mpeg", pdf),
            ("picture.wav", "audio/wav", b"\x89PNG\r\n\x1a\n"),
            ("truncated.wav", "audio/wav", wav()[:-1]),
            ("no-audio.webm", "video/webm", b"\x1a\x45\xdf\xa3"),
            ("playlist.m3u8", "audio/mpeg", b"#EXTM3U\nhttps://example.invalid/audio.wav\n"),
        ]
        for name, mime, payload in cases:
            with self.subTest(name=name), patch("app.masking_audio.run_worker_process", return_value=(1, b"")) as decoder:
                response = self.post(payload, name, mime=mime)
                self.assertEqual(response.status_code, 415, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_audio")
                self.assertNotIn("masked", response.json())
                command = decoder.call_args.args[0]
                self.assertEqual(command[command.index("-map") + 1], "0:a:0")
                self.assertEqual(command[command.index("-protocol_whitelist") + 1], "file")
                formats = command[command.index("-format_whitelist") + 1].split(",")
                self.assertTrue({"concat", "hls", "dash"}.isdisjoint(formats))
                self.assertEqual(list(self.uploads.iterdir()), [])
        with patch("app.masking_audio.run_worker_process") as decoder:
            response = self.post(b"", "empty.wav", mime="audio/wav")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "empty_audio")
        decoder.assert_not_called()

    def test_asr_wav_validation_rejects_pdf_even_with_audio_metadata(self):
        for name, mime in (("document.pdf", "application/pdf"), ("document.wav", "audio/wav"),
                           ("document.mp3", "audio/mpeg")):
            with self.subTest(name=name):
                with patch("app.masking_audio.run_worker_process", return_value=(1, b"")):
                    response = self.client.post("/api/asr/transcribe", data={"language": "ru"},
                                                files={"file": (name, b"%PDF-1.7\n%%EOF\n", mime)})
                self.assertEqual(response.status_code, 415, response.text)
                self.assertEqual(response.json()["error"]["code"], "invalid_audio")
                self.assertEqual(list(self.uploads.iterdir()), [])

    def test_asr_decodes_supported_compressed_uploads_before_model_inference(self):
        ru, en = RecordingAdapter(), RecordingAdapter()
        with TestClient(create_app(self.settings, {"gigaam-multi": ru, "whisper": en})) as client:
            for name, signature in (("source.mp3", b"ID3"), ("source.m4a", b"\x00\x00\x00\x18ftypM4A "),
                                    ("source.flac", b"fLaC"), ("source.ogg", b"OggS")):
                for language, adapter in (("ru", ru), ("en", en)):
                    with self.subTest(name=name, language=language):
                        payload = signature + b"test-only"
                        with patch("app.masking_audio.run_worker_process", side_effect=self.fake_decode(payload, wav())):
                            reply = client.post("/api/asr/transcribe", data={"language": language},
                                                files={"file": (name, payload, "application/octet-stream")})
                        self.assertEqual(reply.status_code, 200, reply.text)
                        path, received_language, audio = adapter.calls[-1]
                        self.assertEqual((path.name, received_language, audio), ("normalized.wav", language, wav()))
                        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_asr_rejects_decoder_failure_and_timeout_before_inference(self):
        adapter = RecordingAdapter()
        with TestClient(create_app(self.settings, {"whisper": adapter})) as client:
            for decoder_result, status, code in (((1, b"private path"), 415, "invalid_audio"),
                                                 (WorkerTimeout(), 504, "asr_timeout")):
                with self.subTest(status=status), patch("app.masking_audio.run_worker_process") as decoder:
                    if isinstance(decoder_result, Exception):
                        decoder.side_effect = decoder_result
                    else:
                        decoder.return_value = decoder_result
                    reply = client.post("/api/asr/transcribe", data={"language": "en"},
                                        files={"file": ("forged.mp3", b"%PDF-1.7", "audio/mpeg")})
                    self.assertEqual(reply.status_code, status, reply.text)
                    self.assertEqual(reply.json()["error"]["code"], code)
                    self.assertNotIn("private path", reply.text)
                    self.assertEqual(list(self.uploads.iterdir()), [])
        self.assertFalse(adapter.calls)

    def test_asr_disconnect_stops_decoding_and_removes_partial_wav(self):
        started = Event()
        adapter = RecordingAdapter()
        app = create_app(self.settings, {"whisper": adapter})
        path = "/api/asr/transcribe"
        request = Request("POST", "http://localhost" + path, data={"language": "en"},
                          files={"file": ("speech.mp3", b"ID3test-only", "audio/mpeg")})
        payload = request.read()
        sent = []
        delivered = False

        def decode(command, _cwd, _request, *, checkpoint, **_):
            Path(command[-1]).write_bytes(b"partially written WAV")
            started.set()
            for _ in range(300):
                checkpoint()
                sleep(0.01)
            self.fail("ASR did not cancel preparation")

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": payload}
            while not started.is_set():
                await asyncio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "path": path, "method": "POST", "query_string": b"",
                 "headers": [(name.lower(), value) for name, value in request.headers.raw]}
        with patch("app.masking_audio.run_worker_process", side_effect=decode):
            asyncio.run(asyncio.wait_for(app(scope, receive, send), timeout=5))
        self.assertEqual(sent[0]["status"], 499)
        self.assertFalse(adapter.calls)
        self.assertEqual(list(self.uploads.iterdir()), [])
