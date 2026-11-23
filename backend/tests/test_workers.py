from contextlib import ExitStack, nullcontext
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_worker(name):
    path = Path(__file__).resolve().parent.parent / "workers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Workers only import standard library/common at import time, no ASR library.
    spec.loader.exec_module(module)
    return module


class WorkerCodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.weights = Path(self.temp.name)
        self.audio = self.weights / "test.wav"
        self.audio.write_bytes(b"test-only stub")

    def gigaam_assets(self):
        config = {"auto_map": {"AutoConfig": "modeling_gigaam.GigaAMConfig", "AutoModel": "modeling_gigaam.GigaAMModel"},
                  "cfg": {"model": {"cfg": {"model_name": "multilingual_ctc", "encoder": {"d_model": 768, "n_layers": 16}}}}}
        (self.weights / "config.json").write_text(json.dumps(config))
        for name in ("modeling_gigaam.py", "pytorch_model.bin"):
            (self.weights / name).write_bytes(b"test-only stub, not a model")
        self.ffmpeg = self.weights / "explicit ffmpeg stub.exe"
        self.ffmpeg.write_bytes(b"test-only stub, never executed")
        return config

    def mock_gigaam(self, result):
        model = type("LocalGigaAMModel", (), {"__module__": "local_test_gigaam"})()
        model.to = Mock(return_value=model)
        model.eval = Mock(return_value=model)
        model.transcribe = Mock(return_value=result)
        factory = Mock(return_value=model)
        torch = SimpleNamespace(set_num_threads=Mock(), inference_mode=nullcontext, float32="mock-float32")
        modules = {"torch": torch, "transformers": SimpleNamespace(AutoModel=SimpleNamespace(from_pretrained=factory)),
                   "local_test_gigaam": SimpleNamespace(run=Mock())}
        return model, factory, modules

    def test_whisper_uses_local_cpu_int8_and_fixed_english(self):
        worker = load_worker("whisper_worker")
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            (self.weights / name).write_text("{}")
        instance = Mock()
        instance.model.is_multilingual = True
        instance.transcribe.return_value = (iter([SimpleNamespace(text="test "), SimpleNamespace(text="text")]), None)
        constructor = Mock(return_value=instance)
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
            self.assertEqual(worker.transcribe(self.audio, self.weights), "test text")
        constructor.assert_called_once_with(str(self.weights), device="cpu", compute_type="int8",
                                            local_files_only=True, cpu_threads=int(os.environ.get("AUDIOMASK_CPU_THREADS", "4")))
        instance.transcribe.assert_called_once_with(str(self.audio), language="en", task="transcribe", vad_filter=False)
        self.assertFalse((self.weights / "preprocessor_config.json").exists())

    def test_whisper_missing_assets_does_not_import_model_package(self):
        worker = load_worker("whisper_worker")
        constructor = Mock()
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
            with self.assertRaises(FileNotFoundError):
                worker.transcribe(self.audio, self.weights)
        constructor.assert_not_called()

    def test_whisper_requires_each_local_asset_to_prevent_download_fallback(self):
        worker = load_worker("whisper_worker")
        names = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
        for name in names:
            (self.weights / name).write_text("test-only stub")
        constructor = Mock()
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
            for name in names:
                path = self.weights / name
                path.unlink()
                with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                    worker.transcribe(self.audio, self.weights)
                path.write_text("test-only stub")
        constructor.assert_not_called()

    def test_gigaam_loads_only_local_ctc_snapshot_on_cpu(self):
        worker = load_worker("gigaam_worker")
        config = self.gigaam_assets()
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only text"))
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}):
            self.assertEqual(worker.transcribe(self.audio, self.weights), "test-only text")
        factory.assert_called_once_with(str(self.weights), local_files_only=True, trust_remote_code=True)
        model.to.assert_called_once_with(device="cpu", dtype="mock-float32")
        model.eval.assert_called_once()
        model.transcribe.assert_called_once_with(str(self.audio))
        config["cfg"]["model"]["cfg"]["encoder"]["d_model"] = 1024
        (self.weights / "config.json").write_text(json.dumps(config))
        with patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}), self.assertRaises(ValueError):
            worker.transcribe(self.audio, self.weights)

    def test_gigaam_rejects_invalid_text_field_and_preserves_empty_text(self):
        worker = load_worker("gigaam_worker")
        self.gigaam_assets()
        for result in ["a bare string", SimpleNamespace(), SimpleNamespace(text=None), SimpleNamespace(text=42)]:
            model, factory, modules = self.mock_gigaam(result)
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}), self.assertRaises(ValueError):
                worker.transcribe(self.audio, self.weights)
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text=""))
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}):
            self.assertEqual(worker.transcribe(self.audio, self.weights), "")

    def test_gigaam_requires_each_local_asset_before_importing_model(self):
        worker = load_worker("gigaam_worker")
        self.gigaam_assets()
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only"))
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}):
            for name in ("config.json", "modeling_gigaam.py", "pytorch_model.bin"):
                path = self.weights / name
                data = path.read_bytes()
                path.unlink()
                with self.subTest(name=name), self.assertRaises(FileNotFoundError):
                    worker.transcribe(self.audio, self.weights)
                path.write_bytes(data)
        factory.assert_not_called()

    def test_gigaam_rejects_remote_custom_code_references(self):
        worker = load_worker("gigaam_worker")
        config = self.gigaam_assets()
        config["auto_map"]["AutoModel"] = "remote/repository--modeling_gigaam.GigaAMModel"
        (self.weights / "config.json").write_text(json.dumps(config))
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only"))
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}), self.assertRaises(ValueError):
            worker.transcribe(self.audio, self.weights)
        factory.assert_not_called()

    def test_gigaam_missing_ffmpeg_never_loads_the_model_or_searches_path(self):
        worker = load_worker("gigaam_worker")
        self.gigaam_assets()
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only"))
        for value in ["", "relative/ffmpeg.exe", str(self.weights / "missing.exe")]:
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": value}), self.assertRaises(worker.FfmpegUnavailable):
                worker.transcribe(self.audio, self.weights)
        factory.assert_not_called()

    def test_gigaam_uses_exact_configured_ffmpeg_and_restores_snapshot_function(self):
        worker = load_worker("gigaam_worker")
        self.gigaam_assets()
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only"))
        original = modules["local_test_gigaam"].run
        def transcribe(audio):
            modules["local_test_gigaam"].run(["ffmpeg", "-nostdin", "-i", audio, "-"], capture_output=True, check=True)
            return SimpleNamespace(text="test-only")
        model.transcribe.side_effect = transcribe
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}):
            self.assertEqual(worker.transcribe(self.audio, self.weights), "test-only")
        command = original.call_args.args[0]
        self.assertEqual(command[:3], [str(self.ffmpeg), "-protocol_whitelist", "file,pipe"])
        self.assertEqual(command[3:], ["-nostdin", "-i", str(self.audio), "-"])
        self.assertFalse(original.call_args.kwargs["shell"])
        self.assertIs(modules["local_test_gigaam"].run, original)
        original.side_effect = OSError("private ffmpeg path")
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {"AUDIOMASK_FFMPEG_PATH": str(self.ffmpeg)}), self.assertRaises(worker.FfmpegUnavailable):
            worker.transcribe(self.audio, self.weights)
        self.assertIs(modules["local_test_gigaam"].run, original)

    def test_gigaam_rejects_unexpected_subprocess_commands(self):
        worker = load_worker("gigaam_worker")
        self.gigaam_assets()
        model, factory, modules = self.mock_gigaam(SimpleNamespace(text="test-only"))
        original = modules["local_test_gigaam"].run
        with patch.dict(sys.modules, modules), worker.local_ffmpeg(model, self.ffmpeg):
            for command, kwargs in [("ffmpeg -i a.wav", {}), (["other-program", "a.wav"], {}),
                                    (["ffmpeg", "a.wav"], {"shell": True})]:
                with self.assertRaises(ValueError):
                    modules["local_test_gigaam"].run(command, **kwargs)
        original.assert_not_called()
        self.assertIs(modules["local_test_gigaam"].run, original)

    def test_worker_exit_codes_for_missing_resources_and_ffmpeg(self):
        common = load_worker("common")
        for exception, expected in [(FileNotFoundError("private weights"), 3), (ImportError("private dependency"), 3),
                                    (common.FfmpegUnavailable(), 4), (ValueError("private model failure"), 2)]:
            request = {"audio": str(self.audio), "weights": str(self.weights), "language": "ru"}
            stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))
            stdout = SimpleNamespace(buffer=io.BytesIO())
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ))
                for obj, name in [(socket.socket, "connect"), (socket.socket, "connect_ex"),
                                  (socket, "create_connection"), (socket, "getaddrinfo"),
                                  (socket, "gethostbyname"), (socket, "gethostbyname_ex")]:
                    stack.enter_context(patch.object(obj, name))
                stack.enter_context(patch.object(sys, "stdin", stdin))
                stack.enter_context(patch.object(sys, "stdout", stdout))
                self.assertEqual(common.execute(Mock(side_effect=exception), "ru"), expected)
            self.assertEqual(stdout.buffer.getvalue(), b"")
    def test_worker_protocol_offline_flags_and_network_guard(self):
        common = load_worker("common")
        request = {"audio": str(self.audio), "weights": str(self.weights), "language": "en"}
        stdin, stdout = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())), SimpleNamespace(buffer=io.BytesIO())

        def fake_transcribe(audio, weights):
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", 1))
            with self.assertRaises(OSError):
                socket.getaddrinfo("example.invalid", 443)
            print("test diagnostics must not appear in protocol")
            return "test text"

        with patch.dict(os.environ), patch.object(socket.socket, "connect"), patch.object(socket.socket, "connect_ex"), \
                patch.object(socket, "create_connection"), patch.object(socket, "getaddrinfo"), \
                patch.object(socket, "gethostbyname"), patch.object(socket, "gethostbyname_ex"), \
                patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            self.assertEqual(common.execute(fake_transcribe, "en"), 0)
        self.assertEqual(json.loads(stdout.buffer.getvalue()), {"text": "test text"})


if __name__ == "__main__":
    unittest.main()
