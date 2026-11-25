"""Local PESQ/ViSQOL worker. Read the request before loading native libraries."""

from importlib import import_module
import json
import logging
import sys
import warnings
import wave


class LatticeUnavailable(Exception):
    pass


class RejectLatticeFallback(logging.Handler):
    def emit(self, record):
        message = record.getMessage().lower()
        if any(word in message for word in ("lattice", "fallback", "fall back", "polynomial")):
            raise LatticeUnavailable()


def create_visqol(use_lattice_model):
    from visqol import VisqolApi

    api = VisqolApi()
    if not use_lattice_model:
        api.create(mode="speech", use_lattice_model=False)
        return api

    # The [lattice] extra for visqol-python 3.8 supplies this runtime.
    if not callable(getattr(import_module("ai_edge_litert.interpreter"), "Interpreter", None)):
        raise LatticeUnavailable()
    # visqol-python can fall back to polynomial scoring when lattice is missing.
    logger = logging.getLogger()
    reject_fallback = RejectLatticeFallback(logging.WARNING)
    logger.addHandler(reject_fallback)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("error", message=r".*(lattice|fall.?back|polynomial).*")
            api.create(mode="speech", use_lattice_model=True)
    finally:
        logger.removeHandler(reject_fallback)
    return api


def read_pcm(path, np):
    with wave.open(path, "rb") as audio:
        if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Unexpected PCM format")
        count = audio.getnframes()
        samples = np.frombuffer(audio.readframes(count), dtype="<i2")
        if not count or samples.size != count:
            raise ValueError("Invalid PCM length")
        return samples


def main():
    request = json.load(sys.stdin)
    metric = request["metric"]
    try:
        import numpy as np

        if metric == "PESQ":
            from pesq import pesq
        elif metric in ("ViSQOL", "ViSQOL_LATTICE"):
            api = create_visqol(metric == "ViSQOL_LATTICE")
        else:
            return 2
    except (ImportError, OSError):
        return 3
    except Exception:
        return 3 if metric in ("ViSQOL", "ViSQOL_LATTICE") else 2

    if request["reference"] is None:
        print(json.dumps({"ready": True}))
        return 0

    reference = read_pcm(request["reference"], np)
    degraded = read_pcm(request["degraded"], np)
    if reference.size != degraded.size:
        return 2
    if any(signal.min() == signal.max() for signal in (reference, degraded)):
        return 4
    if metric == "PESQ":
        value = pesq(16000, reference, degraded, "wb")
    else:
        result = api.measure(request["reference"], request["degraded"])
        value = result.moslqo
    print(json.dumps({"value": float(value)}, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception:
        exit_code = 2
    sys.exit(exit_code)
