"""Dataset validation and WER, using only the Python standard library."""
import csv
import hashlib
import re
import unicodedata
import wave
from pathlib import Path


def tokens(text):
    return re.findall(r"[^\W_]+", unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е'))


def word_errors(reference, hypothesis):
    a, b = tokens(reference), tokens(hypothesis)
    if not a:
        raise ValueError('Reference contains no words after normalization')
    row = list(range(len(b)+1))
    for i, x in enumerate(a, 1):
        nxt = [i]
        for j, y in enumerate(b, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(x != y)))
        row = nxt
    return row[-1], len(a)


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def inspect_wav(path):
    with wave.open(str(path), 'rb') as w:
        channels, width, rate, count, compression, _ = w.getparams()
        if compression != 'NONE' or width not in (1, 2, 3, 4):
            raise ValueError('Only integer PCM WAV 8/16/24/32-bit supported')
        if channels < 1 or rate <= 0 or count <= 0:
            raise ValueError('Empty or invalid WAV')
        total = 0
        while block := w.readframes(65536):
            total += len(block)
        if total != count*channels*width:
            raise ValueError('Truncated WAV samples')
    return dict(channels=channels, bits=width*8, sample_rate=rate, duration_s=count/rate)


def validate(data):
    data = Path(data).resolve()
    rows, errors = [], []
    for language in ('rus', 'eng'):
        expected = {str(i) for i in range(1, 11)}
        for folder, suffix in (('audio', '.wav'), ('text', '.txt')):
            paths = [p for p in (data/language/folder).glob('*') if p.is_file() and p.suffix.lower() == suffix]
            actual = {p.stem for p in paths}
            if actual != expected or len(paths) != 10:
                errors.append(f'{language}/{folder}: expected 1..10; missing={sorted(expected-actual)}, extra={sorted(actual-expected)}, count={len(paths)}')
        for i in range(1, 11):
            wav, txt = data/language/'audio'/f'{i}.wav', data/language/'text'/f'{i}.txt'
            try:
                reference = txt.read_text(encoding='utf-8-sig', errors='strict')
                if '\x00' in reference or not tokens(reference):
                    raise ValueError('Empty reference or NUL characters')
                metadata = inspect_wav(wav)
                rows.append(dict(language=language, id=str(i), wav=str(wav), text=str(txt),
                    wav_sha256=fingerprint(wav), text_sha256=fingerprint(txt), **metadata))
            except (OSError, ValueError, EOFError, wave.Error) as e:
                errors.append(f'{language}/{i}: {e}')
    return rows, errors


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
