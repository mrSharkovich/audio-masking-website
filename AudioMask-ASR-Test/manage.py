"""Explicit environment diagnostics and opt-in model downloads."""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
os.environ.update(CUDA_VISIBLE_DEVICES='-1', HF_HOME=str(ROOT/'.cache'/'huggingface'),
    HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1', TOKENIZERS_PARALLELISM='false')
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '4'


def check_dependencies(model):
    from benchmark import environment
    if environment(require_venv=True):
        return 2
    modules = ['av','numpy','psutil','huggingface_hub']
    modules += ['faster_whisper','ctranslate2','onnxruntime','tokenizers'] if model == 'whisper' else [
        'torch','torchaudio','transformers','hydra','omegaconf','sentencepiece','soundfile']
    for module in modules:
        importlib.import_module(module)
        print('IMPORT OK:', module)
    if model != 'whisper':
        import torch
        from transformers import AutoModel, PreTrainedModel
        print('Torch CPU operation:', (torch.ones(2)+1).tolist())
        if torch.version.cuda is not None:
            raise RuntimeError('Expected a CPU-only torch build; reinstall from official CPU index')
    else:
        import ctranslate2
        if 'int8' not in ctranslate2.get_supported_compute_types('cpu'):
            raise RuntimeError('INT8 is not supported by this virtual CPU')
    print('Imports passed. This does not test model loading or ASR.')
    return 0


def download(model, allowed):
    if not allowed:
        raise ValueError('Download denied: pass --allow-download explicitly')
    from huggingface_hub import HfApi, snapshot_download
    repo, revision = {
        'whisper': ('Systran/faster-whisper-small', 'main'),
        'gigaam-v3': ('ai-sage/GigaAM-v3', 'ctc'),
        'gigaam-multi': ('ai-sage/GigaAM-Multilingual', 'ctc'),
    }[model]
    folder = ROOT/'models'/model
    lock = folder/'download.json'
    if lock.exists():
        commit = json.loads(lock.read_text(encoding='utf-8'))['commit']
    else:
        evidence = ROOT/'compatibility'/'evidence.json'
        audited = json.loads(evidence.read_text(encoding='utf-8')).get('model_revisions', {}).get(model, {}) if evidence.exists() else {}
        commit = audited.get('commit') or HfApi().model_info(repo, revision=revision).sha
    patterns = ['*.json','*.py','*.safetensors','*.bin','*.model','*.txt','*.tiktoken','*.npz']
    snapshot_download(repo_id=repo, revision=commit, local_dir=str(folder),
        allow_patterns=patterns, max_workers=1)
    if not (folder/'config.json').is_file():
        raise RuntimeError('Incomplete download: missing config.json')
    from dataset import fingerprint
    files = {str(p.relative_to(folder)): fingerprint(p) for p in folder.rglob('*')
        if p.is_file() and '.cache' not in p.parts and p.name != 'download.json'}
    lock.write_text(json.dumps(dict(repository=repo, requested_revision=revision, commit=commit,
        files_sha256=files), indent=2), encoding='utf-8')
    print('Downloaded local snapshot:', folder, 'commit:', commit)


def verify_weights(model):
    from dataset import fingerprint
    folder = ROOT/'models'/model
    lock = json.loads((folder/'download.json').read_text(encoding='utf-8'))
    for relative, expected in lock['files_sha256'].items():
        path = folder/relative
        if not path.resolve().is_relative_to(folder.resolve()) or fingerprint(path) != expected:
            raise ValueError('Model snapshot hash mismatch: '+relative)
    print('Local model hashes verified:', model, lock['commit'])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['check-deps','download','verify-weights'])
    p.add_argument('--model', choices=['whisper','gigaam-v3','gigaam-multi'], required=True)
    p.add_argument('--allow-download', action='store_true')
    args = p.parse_args()
    if args.action == 'check-deps':
        return check_dependencies(args.model)
    if args.action == 'verify-weights':
        verify_weights(args.model)
        return 0
    download(args.model, args.allow_download)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f'{type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
