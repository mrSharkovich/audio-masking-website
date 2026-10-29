"""Local advisory PostToolUse review; standard library only, no commands/network.

PASSED means no heuristic findings in the bounded files, never proof of safety.
No integration allowlist is inferred from comments or source configuration:
external audio/text transfers always require human review of explicit approval.
Only event paths are inspected. Private locations are excluded before opening;
referenced paths in source are never dereferenced. Unknown formats fail closed.
"""

import fnmatch
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


ROOT = Path(__file__).absolute().parents[2]
MAX_BYTES = 256 * 1024
MAX_INPUT = 1024 * 1024
MAX_FILES = 40
MAX_FINDINGS = 40
SECONDS = 2
SOURCE = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json',
          '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.xml', '.sh',
          '.ps1', '.bat', '.cmd', '.properties', '.sql', '.html', '.css'}
PRIVATE = {'private', 'secrets', 'credentials', 'algorithm', 'algorithms',
           'closed_algorithm', 'masking_algorithm', 'uploads', 'storage',
           'recordings', 'audio', 'results', 'outputs', 'transcripts',
           '.git', 'node_modules', '.venv', 'venv'}
AUDIO = {'.wav', '.wave', '.mp3', '.flac', '.ogg', '.opus', '.m4a', '.aac',
         '.aif', '.aiff', '.wma', '.mp4', '.webm'}
SECRET = re.compile(
    r'''(?ix)(?:\b(?:api[_-]?key|access[_-]?key|secret(?:[_-]?key)?|token|password|passwd|client[_-]?secret|authorization)\b["']?\s*[:=]\s*["'][^"'\r\n]+["']|\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{15,}|AKIA[A-Z0-9]{16})\b|-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----|https?://[^\s/:'"]+:[^\s/@'"]+@)''')
ABSOLUTE = re.compile(r'''(?i)(?:[a-z]:[\\/]|\\\\[^\\\s]+\\|/(?:home|Users|root|private|mnt|opt|srv)/)[^"'\r\n]*''')
PAYLOAD = re.compile(r'(?i)audio|transcript|transcription|speech|recording|\.wav|\.mp3')
NETWORK = re.compile(r'(?i)https?://|requests\.|httpx\.|aiohttp\.|fetch\s*\(|axios\.|urlopen|urllib\.|WebSocket|sendBeacon|\.post\s*\(|\.upload\s*\(|\.transcriptions\.create|\.responses\.create|\.send\s*\(')


def paths(event: dict) -> list[str]:
    data = event.get('tool_input')
    if event.get('tool_name') == 'apply_patch':
        patch = data if isinstance(data, str) else data.get('command', data.get('patch')) if isinstance(data, dict) else None
        if not isinstance(patch, str):
            raise ValueError()
        names = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M)
    elif isinstance(data, dict):
        names = [data.get('file_path', data.get('path'))]
    else:
        raise ValueError()
    if not names or not all(isinstance(name, str) and name for name in names):
        raise ValueError()
    return list(dict.fromkeys(names))


def local_path(name: str, cwd: str) -> Path:
    """Lexical containment first: never resolve an untrusted external path."""
    if not Path(cwd).is_absolute():
        raise ValueError()
    path = Path(os.path.abspath(os.path.join(cwd, name)))
    path.relative_to(ROOT)
    return path


def readable(path: Path) -> bool:
    current = ROOT
    for part in path.relative_to(ROOT).parts:
        current /= part
        info = current.lstat()
        # Reject Windows junctions/reparse points as well as symlinks.
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            return False
    return stat.S_ISREG(info.st_mode)


def read_text(path: Path) -> str:
    if not readable(path):
        raise ValueError()
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or b'\0' in raw:
        raise ValueError()
    return raw.decode('utf-8-sig')


def classification(path: Path) -> str:
    parts = [p.lower() for p in path.relative_to(ROOT).parts]
    name = parts[-1]
    if parts[0] in {'.codex', '.agents'}:
        return 'skip'
    if (any(p in PRIVATE or re.search(r'closed[_-]?algorithm|private[_-]?algorithm', p) for p in parts)
            or name.startswith('.env') or path.suffix.lower() in AUDIO | {'.pem', '.key', '.p12', '.pfx'}
            or name.startswith(('id_rsa', 'id_ed25519'))
            or any(word in name for word in ('credential', 'secret', 'masking_algorithm'))):
        return 'private'
    if parts[0] in {'.codex', '.agents', 'docs', 'openspec'} or path.suffix.lower() in {'.md', '.mdx', '.rst', '.txt'}:
        return 'skip'
    return 'scan' if path.suffix.lower() in SOURCE or name in {'.gitignore', 'dockerfile', 'makefile'} else 'unknown'


def findings(text: str) -> list[tuple[int, str]]:
    result = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        if SECRET.search(line):
            result.append((number, 'hardcoded-secret'))
        if ABSOLUTE.search(line):
            result.append((number, 'absolute-local-path'))
        # A bounded window catches ordinary multiline request bodies. Also
        # flag SDK transfer calls even if their payload variable is opaque.
        if NETWORK.search(line):
            context = '\n'.join(lines[max(0, number - 9):number + 8])
            if PAYLOAD.search(context) or re.search(r'(?i)\.transcriptions\.create', line):
                result.append((number, 'possible-external-audio-or-transcript-transfer; approval-unverified'))
        if len(result) >= MAX_FINDINGS:
            break
    return result


def ignored(probe: str, rules: list[str]) -> bool:
    """Conservative subset of gitignore; complex syntax never proves safety."""
    protected = False
    for rule in rules:
        if not rule or rule.startswith('#'):
            continue
        negative = rule.startswith('!')
        pattern = rule[1:] if negative else rule
        # fnmatch supports ordinary bracket classes such as [cod] and [!a].
        # POSIX classes and Git's ^ negation have different semantics;
        # keep those unverified rather than claiming protection.
        if ('\\' in pattern or '[[:' in pattern or '[^' in pattern
                or pattern.endswith(' ')):
            raise ValueError()
        anchored = pattern.startswith('/')
        pattern = pattern.lstrip('/')
        directory = pattern.endswith('/')
        pattern = pattern.rstrip('/')
        parts = probe.split('/')
        candidates = ['/'.join(parts[:n]) for n in range(1, len(parts) + (not directory))]
        if '/' not in pattern and not anchored:
            matched = any(fnmatch.fnmatchcase(p, pattern) for p in (parts[:-1] if directory else parts))
        else:
            matched = any(fnmatch.fnmatchcase(p, pattern) for p in candidates)
        if matched:
            protected = not negative
    return protected


def ignore_findings() -> list[str]:
    try:
        rules = read_text(ROOT / '.gitignore').splitlines()
        groups = {
            'env-protection': ['.env', '.env.local', 'backend/.env', 'backend/.env.local'],
            'secret-protection': ['secrets/probe.bin', 'credentials/probe.bin', 'private/probe.bin', 'backend/secrets/probe.bin'],
            'key-protection': ['probe.pem', 'probe.key', 'probe.p12', 'probe.pfx', 'id_rsa_probe', 'backend/id_ed25519_probe'],
            'audio-protection': ['uploads/probe.bin', 'storage/probe.bin', 'recordings/probe.bin', 'backend/uploads/probe.bin',
                                 *['probe' + suffix for suffix in sorted(AUDIO)]],
            'results-protection': ['outputs/probe.bin', 'storage/results/probe.bin', 'results/probe.bin', 'transcripts/probe.txt'],
            'temporary-protection': ['tmp/probe.bin', 'temp/probe.bin', 'backend/tmp/probe.bin'],
        }
        return [f'.gitignore:1: {kind} (representative paths not protected)'
                for kind, probes in groups.items() if not all(ignored(p, rules) for p in probes)]
    except (OSError, ValueError, UnicodeError):
        return ['.gitignore:1: protection-unverified (unreadable, oversized or unsupported rules)']


def review(event: dict) -> str:
    names = paths(event)
    notes = []
    scanned = 0
    relevant = False
    deadline = time.monotonic() + SECONDS
    for index, name in enumerate(names):
        if index >= MAX_FILES or time.monotonic() > deadline:
            notes.append('event:1: review-limit; remaining files unverified')
            break
        try:
            path = local_path(name, event.get('cwd', str(ROOT)))
        except (ValueError, OSError, TypeError):
            notes.append('event:1: external-or-invalid-path; not accessed')
            continue
        kind = classification(path)
        if kind == 'skip':
            continue
        relevant = True
        if kind == 'private':
            notes.append('event:1: protected-file; content and name withheld, not read')
            continue
        # No input snippets, exception messages or absolute paths in output.
        label = path.relative_to(ROOT).as_posix()
        if SECRET.search(label) or len(label) > 180:
            label = 'changed-file'
        if kind == 'unknown':
            notes.append(f'{label}:1: unsupported-file-type; not read')
            continue
        try:
            text = read_text(path)
            scanned += 1
            notes.extend(f'{label}:{line}: {issue}' for line, issue in findings(text))
        except (OSError, ValueError, UnicodeError):
            notes.append(f'{label}:1: content-unverified (unavailable, link, binary or size limit)')
        if len(notes) >= MAX_FINDINGS:
            notes = notes[:MAX_FINDINGS] + ['event:1: finding-limit; review incomplete']
            break
    if relevant:
        notes.extend(ignore_findings())
    if notes:
        return 'REVIEW\n' + '\n'.join(notes)
    if not scanned:
        return 'SKIPPED: documentation or Harness only; no source/configuration checked'
    return 'PASSED: bounded heuristic review; no risks detected, not a safety guarantee'


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError()
        if event.get('hook_event_name') != 'PostToolUse' or event.get('tool_name') not in {'apply_patch', 'Edit', 'Write'}:
            message = 'SKIPPED: unsupported event'
        else:
            message = review(event)
    except Exception:
        # Never expose exception text: it can contain payloads and local paths.
        message = 'REVIEW: event:1: check-incomplete; invalid input or local inspection error'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',
          'additionalContext': 'Secrets & Privacy Check: ' + message}}, ensure_ascii=True))


if __name__ == '__main__':
    main()
