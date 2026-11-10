from contextlib import nullcontext
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

    def test_whisper_uses_local_cpu_int8_and_fixed_english(self):
        worker = load_worker("whisper_worker")
        for name in ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json"):
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

    def test_whisper_missing_assets_does_not_import_model_package(self):
        worker = load_worker("whisper_worker")
        constructor = Mock()
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
            with self.assertRaises(FileNotFoundError):
                worker.transcribe(self.audio, self.weights)
        constructor.assert_not_called()

    def test_gigaam_loads_only_local_ctc_snapshot_on_cpu(self):
        worker = load_worker("gigaam_worker")
        config = {"cfg": {"model": {"cfg": {"model_name": "multilingual_ctc", "encoder": {"d_model": 768, "n_layers": 16}}}}}
        (self.weights / "config.json").write_text(json.dumps(config))
        model = Mock()
        model.to.return_value.eval.return_value = model
        model.transcribe.return_value = "test-only text"
        factory = Mock(return_value=model)
        torch = SimpleNamespace(set_num_threads=Mock(), inference_mode=nullcontext)
        transformers = SimpleNamespace(AutoModel=SimpleNamespace(from_pretrained=factory))
        with patch.dict(sys.modules, {"torch": torch, "transformers": transformers}):
            self.assertEqual(worker.transcribe(self.audio, self.weights), "test-only text")
        factory.assert_called_once_with(str(self.weights), local_files_only=True, trust_remote_code=True)
        model.to.assert_called_once_with("cpu")
        model.transcribe.assert_called_once_with(str(self.audio))
        config["cfg"]["model"]["cfg"]["encoder"]["d_model"] = 1024
        (self.weights / "config.json").write_text(json.dumps(config))
        with self.assertRaises(ValueError):
            worker.transcribe(self.audio, self.weights)

    def test_worker_protocol_offline_flags_and_network_guard(self):
        common = load_worker("common")
        request = {"audio": str(self.audio), "weights": str(self.weights), "language": "en"}
        stdin, stdout = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())), SimpleNamespace(buffer=io.BytesIO())

        def fake_transcribe(audio, weights):
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")
            with self.assertRaises(OSError):
                socket.create_connection(("127.0.0.1", 1))
            print("test diagnostics must not appear in protocol")
            return "test text"

        with patch.dict(os.environ), patch.object(socket.socket, "connect"), patch.object(socket.socket, "connect_ex"), \
                patch.object(socket, "create_connection"), patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout):
            self.assertEqual(common.execute(fake_transcribe, "en"), 0)
        self.assertEqual(json.loads(stdout.buffer.getvalue()), {"text": "test text"})


if __name__ == "__main__":
    unittest.main()
