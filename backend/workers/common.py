"""Worker protocol and offline setup; no model imports at module import time."""
from contextlib import redirect_stdout, redirect_stderr
import json
import os
from pathlib import Path
import socket
import sys


def execute(transcribe, language: str):
    # Parent assigns process containment before writing this startup gate.
    request = json.loads(sys.stdin.buffer.readline(65536))
    if set(request) != {"audio", "weights", "language"} or request["language"] != language:
        return 2
    audio, weights = Path(request["audio"]), Path(request["weights"])
    if not audio.is_file() or not weights.is_dir() or not weights.is_absolute():
        return 3
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1", CUDA_VISIBLE_DEVICES="")

    def deny_network(*args, **kwargs):
        raise OSError("Network is disabled in ASR workers")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    try:
        # Library diagnostics may contain paths/text. Discard rather than persist
        # or forward them; stdout contains only our bounded UTF-8 JSON protocol.
        with open(os.devnull, "w") as null, redirect_stdout(null), redirect_stderr(null):
            text = transcribe(audio, weights)
        if not isinstance(text, str):
            return 2
        sys.stdout.buffer.write(json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    except (ImportError, FileNotFoundError, OSError):
        return 3
    except Exception:
        return 2


def main(transcribe, language: str):
    try:
        code = execute(transcribe, language)
    except Exception:
        code = 2
    raise SystemExit(code)
