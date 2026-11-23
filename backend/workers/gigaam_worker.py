"""Local Transformers snapshot of GigaAM-Multilingual revision ctc (220M)."""
import json
import os
from pathlib import Path
import sys
from contextlib import contextmanager
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FfmpegUnavailable, main


@contextmanager
def local_ffmpeg(model, executable: Path):
    # The pinned GigaAM snapshot imports subprocess.run as a module-level `run`
    # and hardcodes argv[0] = "ffmpeg". Bind only that call to the configured
    # executable. Other helpers can resolve it through the worker's PATH.
    module = sys.modules[type(model).__module__]
    original_run = module.run

    def run(command, *args, **kwargs):
        if not isinstance(command, (list, tuple)) or not command or command[0] != "ffmpeg" or kwargs.get("shell"):
            raise ValueError("Unexpected model subprocess command")
        command = [str(executable), "-protocol_whitelist", "file,pipe", *command[1:]]
        kwargs["shell"] = False
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        try:
            return original_run(command, *args, **kwargs)
        except OSError as exc:
            raise FfmpegUnavailable() from exc

    module.run = run
    try:
        yield
    finally:
        module.run = original_run


def transcribe(audio: Path, weights: Path) -> str:
    for name in ("config.json", "modeling_gigaam.py", "pytorch_model.bin"):
        if not (weights / name).is_file():
            raise FileNotFoundError()
    configured_ffmpeg = os.environ.get("AUDIOMASK_FFMPEG_PATH")
    ffmpeg = Path(configured_ffmpeg) if configured_ffmpeg else None
    if ffmpeg is None or not ffmpeg.is_absolute() or not ffmpeg.is_file():
        raise FfmpegUnavailable()
    config_path = weights / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model_config = config.get("cfg", {}).get("model", {}).get("cfg", {})
    if (model_config.get("model_name") != "multilingual_ctc"
            or model_config.get("encoder", {}).get("d_model") != 768
            or model_config.get("encoder", {}).get("n_layers") != 16):
        raise ValueError("Expected GigaAM-Multilingual ctc 220M snapshot")
    if config.get("auto_map") != {"AutoConfig": "modeling_gigaam.GigaAMConfig", "AutoModel": "modeling_gigaam.GigaAMModel"}:
        raise ValueError("Expected custom code from the local GigaAM snapshot")
    import torch
    from transformers import AutoModel
    torch.set_num_threads(int(os.environ.get("AUDIOMASK_CPU_THREADS", "4")))
    # trust_remote_code allows the custom Python code already present in the
    # trusted local snapshot. local_files_only/offline flags prevent fetching it.
    model = AutoModel.from_pretrained(str(weights), local_files_only=True, trust_remote_code=True)
    model = model.to(device="cpu", dtype=torch.float32).eval()
    with local_ffmpeg(model, ffmpeg), torch.inference_mode():
        result = model.transcribe(str(audio))
    text = getattr(result, "text", None)
    if not isinstance(text, str):
        raise ValueError("GigaAM returned no text field")
    return text


if __name__ == "__main__":
    main(transcribe, "ru")
