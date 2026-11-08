"""One model per process. Never downloads weights or sends audio over the network."""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import wave

ROOT = Path(__file__).resolve().parent
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '4'
os.environ.update(CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
    HF_HOME=str(ROOT/'.cache'/'huggingface'), HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
from dataset import validate, write_csv, word_errors, fingerprint


def split_audio(source, folder):
    """Same contiguous <=20 second windows for all models, without VAD or overlap."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    with wave.open(str(source), 'rb') as stream:
        while block := stream.readframes(20*16000):
            path = folder/f'{len(paths):05d}.wav'
            with wave.open(str(path), 'wb') as out:
                out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                out.writeframes(block)
            paths.append(path)
    return paths


def main():
    p = argparse.ArgumentParser()
    for name in ('model', 'data', 'output', 'weights'):
        p.add_argument('--'+name, required=True)
    args = p.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    from manage import verify_weights
    verify_weights(args.model)
    rows, errors = validate(args.data)
    if errors:
        raise ValueError('\n'.join(errors))
    selected = [r for r in rows if args.model != 'gigaam-v3' or r['language'] == 'rus']
    write_csv(out/'dataset.csv', rows)
    from prepare_audio import prepare
    prepared = {}
    started = time.perf_counter()
    for r in selected:
        audio = prepare(r['wav'], out/'audio'/r['language']/f"{r['id']}.wav")
        prepared[r['language'],r['id']] = split_audio(audio, out/'chunks'/r['language']/r['id'])
    prep_s = time.perf_counter()-started
    module = {'whisper':'whisper_model', 'gigaam-v3':'gigaam_v3', 'gigaam-multi':'gigaam_multilingual'}[args.model]
    started = time.perf_counter()
    recognizer = importlib.import_module(module).Recognizer(args.weights)
    load_s = time.perf_counter()-started
    lock = Path(args.weights)/'download.json'
    meta = dict(model=args.model, load_s=load_s, preparation_s=prep_s,
        python=sys.version, platform=platform.platform(), threads=4, device='cpu',
        chunk_seconds=20, warmup=False, vad=False,
        weights=json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else 'untracked local files',
        versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions()})
    (out/'metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    results = []
    for r in selected:
        row = dict(model=args.model, language=r['language'], id=r['id'], status='error',
            duration_s=r['duration_s'], recognition_s='', rtf='', errors='', reference_words='', wer='', error='')
        started = time.perf_counter()
        try:
            hypothesis = ' '.join(recognizer.transcribe(path, r['language']).strip()
                for path in prepared[r['language'],r['id']])
            elapsed = time.perf_counter()-started
            edits, words = word_errors(Path(r['text']).read_text(encoding='utf-8-sig'), hypothesis)
            dest = out/'transcripts'/r['language']
            dest.mkdir(parents=True, exist_ok=True)
            (dest/f"{r['id']}.txt").write_text(hypothesis, encoding='utf-8')
            row.update(status='ok', recognition_s=elapsed, rtf=elapsed/r['duration_s'],
                errors=edits, reference_words=words, wer=edits/words)
        except Exception as e:
            row.update(error=f'{type(e).__name__}: {e}', recognition_s=time.perf_counter()-started)
        results.append(row)
        write_csv(out/'results.csv', results)
        print(f"{r['language']}/{r['id']}: {row['status']}", flush=True)
    for r in rows:
        if fingerprint(r['wav']) != r['wav_sha256'] or fingerprint(r['text']) != r['text_sha256']:
            raise RuntimeError('Dataset changed during experiment; discard comparison')
    return 2 if any(r['status'] != 'ok' for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
