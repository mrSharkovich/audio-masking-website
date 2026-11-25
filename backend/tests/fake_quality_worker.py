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
for path in (reference, degraded):
    with wave.open(str(path), "rb") as file:
        assert (file.getframerate(), file.getnchannels(), file.getsampwidth(), file.getnframes()) == (16000, 1, 2, 16000)

if Path(__file__).stem == "ordered":
    pair = ("original" if reference.stem == "normalized" else reference.stem, degraded.stem)
    value = {("original", "masked"): 2, ("original", "demasked"): 3, ("masked", "demasked"): 4}[pair]
    offset = {"PESQ": 0, "ViSQOL": 0.1, "ViSQOL_LATTICE": 0.2}[metric]
    print(json.dumps({"value": value + offset}))
    sys.exit(0)

if Path(__file__).stem == "slow" and metric == "PESQ":
    (Path(__file__).parent / "started").write_text("started")
    time.sleep(30)
if Path(__file__).stem == "crash" and metric == "PESQ":
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
