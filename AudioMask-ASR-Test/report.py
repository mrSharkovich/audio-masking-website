import csv
import json
from pathlib import Path
from dataset import write_csv


def build_report(run):
    run = Path(run)
    statuses = sorted(run.glob('*.status.json'))
    if not statuses:
        raise ValueError('Select one experiment directory containing *.status.json')
    lines = ['# AudioMask: ASR comparison', '',
        'WER = total word edits / total reference words, separately by language. Lower is better.',
        'Normalization: NFKC, casefold, ё→е, Unicode alphanumeric tokens. Digits are not expanded.',
        'RAM: process-tree RSS sampled every 0.2 s; an approximate peak including preparation and loading.',
        'Load time includes model imports, excludes audio conversion and weight download.',
        'ASR time includes full decoding of all chunks, excludes conversion and WER calculation.',
        'All models: contiguous 20-second chunks, no overlap/VAD, no warm-up.', '',
        '| Model | Language | Success/expected | WER | Load s | ASR s | RTF | Peak MiB | Status |',
        '|---|---|---|---|---|---|---|---|---|']
    summary, signatures = [], set()
    for status_path in statuses:
        status = json.loads(status_path.read_text(encoding='utf-8'))
        model = status['model']
        folder = run/model
        rows = []
        if (folder/'results.csv').exists():
            with (folder/'results.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
        if (folder/'dataset.csv').exists():
            with (folder/'dataset.csv').open(encoding='utf-8-sig', newline='') as stream:
                signatures.add(tuple((r['language'],r['id'],r['wav_sha256'],r['text_sha256']) for r in csv.DictReader(stream)))
        meta = json.loads((folder/'metadata.json').read_text(encoding='utf-8')) if (folder/'metadata.json').exists() else {}
        for language in ('rus','eng'):
            supported = not (model == 'gigaam-v3' and language == 'eng')
            good = [r for r in rows if r['language'] == language and r['status'] == 'ok']
            n = sum(int(r['reference_words']) for r in good)
            edits = sum(int(r['errors']) for r in good)
            seconds = sum(float(r['recognition_s']) for r in good)
            duration = sum(float(r['duration_s']) for r in good)
            complete = supported and len(good) == 10 and status['status'] == 'ok'
            row = dict(model=model, language=language, success=len(good), expected=10 if supported else 0,
                wer=edits/n if n and complete else '', partial_wer=edits/n if n else '',
                load_s=meta.get('load_s',''), recognition_s=seconds, rtf=seconds/duration if duration else '',
                peak_rss_mib=status['peak_rss_mib'], windows_peak_worker_mib=status.get('windows_peak_worker_mib',''),
                status='complete' if complete else 'incomplete' if supported else 'unsupported')
            summary.append(row)
            lines.append('| '+' | '.join(str(row[k]) for k in ('model','language'))+f" | {len(good)}/{row['expected']} | "+
                ' | '.join(str(row[k]) for k in ('wer','load_s','recognition_s','rtf','peak_rss_mib','status'))+' |')
        if status['reason']:
            lines.extend(['',f"{model}: {status['reason']}"])
    if len(signatures) > 1:
        lines.extend(['', '**INVALID COMPARISON: dataset hashes differ between models.**'])
    lines.extend(['', 'Incomplete runs have no final WER; partial_wer in summary.csv is diagnostic only.',
        'WER is a ratio (multiply by 100 for percent); it can exceed 1. RTF < 1 means faster than real time.',
        '20 recordings are a small sample. These results do not establish general model superiority.',
        'Whisper uses INT8 beam=5; GigaAM CTC uses CPU FP32 and greedy decoding.',
        'Chunk boundaries can affect accuracy; do not compare with published full-utterance WER.',
        'Raw transcripts: model/transcripts/{rus,eng}/*.txt. Environment: model/metadata.json.',
        'Original hashes and audio metadata: model/dataset.csv. Copies: model/audio/ and model/chunks/.'])
    write_csv(run/'summary.csv', summary)
    (run/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
