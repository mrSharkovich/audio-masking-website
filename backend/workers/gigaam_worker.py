"""Local Transformers snapshot of GigaAM-Multilingual revision ctc (220M)."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import main


def transcribe(audio: Path, weights: Path) -> str:
    config_path = weights / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    model_config = config.get("cfg", {}).get("model", {}).get("cfg", {})
    if (model_config.get("model_name") != "multilingual_ctc"
            or model_config.get("encoder", {}).get("d_model") != 768
            or model_config.get("encoder", {}).get("n_layers") != 16):
        raise ValueError("Expected GigaAM-Multilingual ctc 220M snapshot")
    import torch
    from transformers import AutoModel
    torch.set_num_threads(int(os.environ.get("AUDIOMASK_CPU_THREADS", "4")))
    # trust_remote_code allows the custom Python code already present in the
    # trusted local snapshot. local_files_only/offline flags prevent fetching it.
    model = AutoModel.from_pretrained(str(weights), local_files_only=True, trust_remote_code=True)
    model = model.to("cpu").eval()
    with torch.inference_mode():
        return model.transcribe(str(audio))


if __name__ == "__main__":
    main(transcribe, "ru")
