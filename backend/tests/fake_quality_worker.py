"""Test-only process for the quality JSON protocol. Produces synthetic responses."""

import json
from pathlib import Path
import sys
import time
import wave


request = json.load(sys.stdin)
metric = request["metric"]
if request["reference"] is None:
    if metric == "ViSQOL":
        sys.exit(3)
    print('{"ready":true}')
    sys.exit(0)

reference = Path(request["reference"])
degraded = Path(request["degraded"])
scenario = Path(__file__).stem


def read(path):
    with wave.open(str(path), "rb") as file:
        assert (file.getframerate(), file.getnchannels(), file.getsampwidth()) == (16000, 1, 2)
        return file.readframes(file.getnframes())


reference_pcm, degraded_pcm = read(reference), read(degraded)
assert len(reference_pcm) == len(degraded_pcm)
unpadded = request.get("unpadded_frames")
if unpadded is not None:
    assert reference.name == f"original-for-{degraded.stem}.wav"
    original_pcm = read(reference.with_name("original.wav"))
    assert len(original_pcm) == 2 * unpadded < len(reference_pcm)
    assert reference_pcm == original_pcm + bytes(len(reference_pcm) - len(original_pcm))
    if scenario == "padding":
        assert original_pcm == (b"\x34\x12\xcc\xed" * ((unpadded + 1) // 2))[:2 * unpadded]
        assert degraded_pcm == bytes(len(degraded_pcm))
else:
    assert reference.stem in ("original", "normalized", "masked")
    assert len(reference_pcm) == 32000

if scenario in ("ordered", "padding"):
    pair = ("original" if unpadded is not None or reference.stem == "normalized" else reference.stem, degraded.stem)
    value = {("original", "masked"): 2, ("original", "demasked"): 3, ("masked", "demasked"): 4}[pair]
    offset = {"PESQ": 0, "ViSQOL": 0.1, "ViSQOL_LATTICE": 0.2}[metric]
    print(json.dumps({"value": value + offset}))
    sys.exit(0)

if scenario == "slow" and metric == "PESQ":
    (Path(__file__).parent / "started").write_text("started")
    time.sleep(30)
if scenario == "crash" and metric == "PESQ":
    print("private worker detail", file=sys.stderr)
    sys.exit(2)
if degraded.stem == "masked":
    if metric == "ViSQOL":
        sys.exit(3)
    print('{"value":4.321}' if metric == "PESQ" else '{"value":4.2}')
else:
    if metric == "PESQ":
        print('{"value":NaN}')
    elif metric == "ViSQOL":
        print('{"value":3.2}')
    else:
        sys.exit(3)
