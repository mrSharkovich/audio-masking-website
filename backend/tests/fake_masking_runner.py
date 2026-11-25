"""Process-protocol fixture. Uses only synthetic input supplied by tests."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave


request = json.load(sys.stdin)
assert set(request) == {"protocol_version", "input_path", "masked_output_path", "demasked_output_path",
                        "mode", "matrix_size"}
assert request["protocol_version"] == 1
assert request["mode"] == "one-sided"
assert request["matrix_size"] == 16
source = Path(request["input_path"])
masked = Path(request["masked_output_path"])
demasked = Path(request["demasked_output_path"])
assert source.is_absolute() and masked.parent == demasked.parent == source.parent
assert masked != demasked and not masked.exists() and not demasked.exists()
with wave.open(str(source), "rb") as audio:
    assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)

scenario = Path(sys.argv[0]).stem
shutil.copyfile(source, masked)
if scenario != "missing":
    shutil.copyfile(source, demasked)
if scenario == "invalid_wav":
    demasked.write_bytes(b"invalid output")
if scenario == "wait":
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
    Path("child.pid").write_text(str(child.pid))
    Path("started").touch()
    time.sleep(60)
if scenario == "failure":
    sys.stderr.write("private runner data")
    raise SystemExit(4)
if scenario == "bad_json":
    print("private runner data")
else:
    print(json.dumps({"protocol_version": 1, "status": "ok",
                      "applied_matrix_size": True if scenario == "bad_matrix" else 4}))
