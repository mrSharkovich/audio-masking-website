"""Test-only worker: never imports ASR packages or generates real transcripts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

request = json.loads(sys.stdin.readline())
weights = Path(request["weights"])
mode = (weights / "mode").read_text()
assert os.environ["HF_HUB_OFFLINE"] == "1"
assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
with wave.open(request["audio"], "rb") as audio:
    assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
(weights / "ready").write_text("ready")
if mode in ("tree_timeout", "tree_success"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    (weights / "child.pid").write_text(str(child.pid))
if mode in ("timeout", "tree_timeout"):
    time.sleep(60)
if mode == "unavailable":
    sys.exit(3)
if mode == "failure":
    sys.stderr.write("private details must not be exposed")
    sys.exit(2)
if mode == "invalid":
    print("not-json")
elif mode == "schema":
    print('{"text":42}')
elif mode == "flood":
    sys.stdout.write("x" * 1000000)
elif mode == "stderr_flood":
    sys.stderr.write("x" * 1000000)
else:
    print(json.dumps({"text": "test-only:" + request["language"]}))
