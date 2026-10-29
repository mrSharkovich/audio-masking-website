"""Local, lossy summaries from event metadata; never reads transcripts/source.

No free-form message excerpts are persisted: tasks/checks/limitations use fixed
labels, files use conservative relative-path syntax. Results are self-reported,
not independently verified. Unrecognized information remains UNKNOWN.
Stop uses only an informational systemMessage (never a blocking decision).
SessionEnd has no response body and always exits successfully, including errors.
Python standard library only. Store is bounded and outside the repository.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


ROOT = Path(__file__).absolute().parents[2]
MAX_INPUT = 256 * 1024
MAX_MESSAGE = 24000
MAX_RECORDS = 30
MAX_SESSIONS = 100
MAX_STATE = 65536
MAX_SUMMARY = 24000
MAX_ITEMS = 8
STATUSES = ('PASSED', 'FAILED', 'SKIPPED', 'UNKNOWN')
TASKS = {
    'Session Summary': r'session summary|сводк\w*\s+сесси',
    'Documentation Check': r'documentation check',
    'Agent Role Check': r'agent role check',
    'Dependency Guard': r'dependency guard',
    'Secrets & Privacy Check': r'secrets\s*&\s*privacy check',
    'Security Check': r'security check',
    'Test Runner': r'test runner',
    'Code Quality Check': r'code quality check',
    'QA Check': r'qa check',
    'Spec Compliance Check': r'spec compliance check',
    'public API': r'публичн\w*\s+api|public api',
    'audio upload': r'загруз\w*\s+аудио|audio upload',
    'audio processing': r'обработ\w*\s+аудио|audio processing',
    'frontend': r'\bfrontend\b|интерфейс',
    'backend': r'\bbackend\b',
    'documentation': r'документац|\bdocumentation\b',
}
CHECKS = {
    'Python syntax': r'синтаксис\w*\s+python|python syntax|py_compile',
    'JSON configuration': r'\bjson\b',
    'tests': r'\btests?\b|pytest|тест\w*|провер\w*',
    'lint': r'\blint\b|eslint|ruff|линтер',
    'build': r'\bbuild\b|сборк',
    'types': r'typecheck|tsc|провер\w*\s+тип',
    'existing hooks preserved': r'сохранност|неизменност|хеш\w*|hash\w*|unchanged',
    'real Codex session': r'реальн\w*\s+сесси\w*\s+codex|real codex session',
    'real application': r'реальн\w*\s+приложен|real application',
}
FAILED = re.compile(r'(?i)\bfailed\b|\bfail\b|\berror\b|\binvalid\b|not\s+pass|ошибк|некоррект|не\s+коррект|не\s+прош\w*|не\s+пройден\w*|неуспеш|провален')
SKIPPED = re.compile(r'(?i)\bskipped\b|not\s+(?:run|tested|executed)|не\s+(?:запуск\w*|выполня\w*|проверял\w*|проверен\w*)|пропущ\w*')
PASSED = re.compile(r'(?i)\bpassed\b|\bpass\b|\bunchanged\b|успеш\w*|прошл\w*|пройден\w*|коррект\w*|совпада\w*|сохранены|неизменны')
DONE = re.compile(r'(?i)\bcompleted\b|\bimplemented\b|\bcreated\b|\bfixed\b|создан\w*|настроен\w*|добавлен\w*|исправлен\w*|реализован\w*|завершен\w*|завершён\w*')
FILE_ACTION = re.compile(r'(?i)измен\w*|создан\w*|обновл\w*|добавлен\w*|исправлен\w*|changed|created|updated|modified|added')
SENSITIVE = re.compile(r'(?i)api[_-]?key|token|password|passwd|secret|credential|authorization|транскрип|transcript|распознанн\w*\s+текст|sk-[\w-]{8,}|gh[pousr]_[\w]+|-----BEGIN|https?://|[A-Z]:[\\/]|\\\\')
FILE = re.compile(r'`([^`\r\n]{1,160})`|(?<![\w/\\])((?:\.codex/|backend/|frontend/|src/|docs/)[A-Za-z0-9_./-]{1,140}\.[A-Za-z0-9]{1,8})(?![\w/])')
SAFE_ROOT_FILES = {'README.md', 'package.json', 'package-lock.json', 'pyproject.toml', 'requirements.txt', '.gitignore'}
SUFFIXES = {'.py', '.ts', '.tsx', '.js', '.jsx', '.json', '.toml', '.yaml', '.yml', '.md', '.css', '.html', '.txt'}


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def status(text: str) -> str:
    text = re.sub(r'(?i)без\s+ошибок|without\s+errors|no\s+errors', '', text)
    if FAILED.search(text):
        return 'FAILED'
    if SKIPPED.search(text):
        return 'SKIPPED'
    if PASSED.search(text):
        return 'PASSED'
    return 'UNKNOWN'


def safe_file(value: str) -> bool:
    # No absolute paths, arbitrary user filenames, audio, .env or private trees.
    if value in SAFE_ROOT_FILES:
        return True
    if SENSITIVE.search(value) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,140}', value):
        return False
    parts = value.split('/')
    if any(p in {'', '.', '..'} or len(p) > 40 for p in parts):
        return False
    if parts[0] not in {'.codex', 'backend', 'frontend', 'src', 'docs'}:
        return False
    if any(re.search(r'(?i)private|algorithm|storage|upload|recording|result|audio|\.env', p) for p in parts):
        return False
    # Restrict opaque identifiers likely to contain sensitive data.
    if any(re.search(r'[0-9]{4}|[A-Za-z0-9_-]{24,}', p.rsplit('.', 1)[0]) for p in parts):
        return False
    return Path(value).suffix.lower() in SUFFIXES


def extract(message: object) -> dict:
    record = {'source': 'last_assistant_message; self-reported', 'tasks': [],
              'files': [], 'checks': [], 'limitations': [], 'extraction': 'UNKNOWN'}
    if not isinstance(message, str) or not message.strip():
        return record
    if len(message) > MAX_MESSAGE:
        record['limitations'].append('message-limit; remainder not inspected')
    clauses = re.split(r'[\n;!?]|\.\s+(?=[А-ЯA-Z])', message[:MAX_MESSAGE])
    if len(clauses) > 100:
        record['limitations'].append('bounded inspection')
    for clause in clauses[:100]:
        if SENSITIVE.search(clause):
            if 'sensitive-clause-omitted' not in record['limitations']:
                record['limitations'].append('sensitive-clause-omitted')
            continue
        for label, pattern in TASKS.items():
            if re.search(pattern, clause, re.I) and (DONE.search(clause) or FAILED.search(clause)):
                task_status = 'FAILED' if FAILED.search(clause) else ('UNKNOWN' if re.search(r'(?i)\bне\s|\bnot\s', clause) else 'PASSED')
                item = {'name': label, 'status': task_status}
                if item not in record['tasks'] and len(record['tasks']) < MAX_ITEMS:
                    record['tasks'].append(item)
        for label, pattern in CHECKS.items():
            if re.search(pattern, clause, re.I):
                item = {'name': label, 'status': status(clause)}
                if item not in record['checks'] and len(record['checks']) < MAX_ITEMS:
                    record['checks'].append(item)
        if FILE_ACTION.search(clause):
            for match in FILE.finditer(clause):
                value = match[1] or match[2]
                if safe_file(value) and value not in record['files'] and len(record['files']) < MAX_ITEMS:
                    record['files'].append(value)
        for pattern, label in (
            (r'эврист|heuristic', 'heuristic analysis only'),
            (r'не\s+доказ|not proven|not verified', 'independent verification unavailable'),
            (r'недоступ|unavailable', 'component or verification unavailable'),
            (r'лимит|limit', 'bounded inspection'),
            (r'реальн\w*\s+приложен\w*.*не\s+провер|real application.*not tested', 'real application not tested'),
            (r'реальн\w*\s+сесси.*не\s+провер|real codex session.*not tested', 'real Codex session not tested'),
        ):
            if re.search(pattern, clause, re.I) and label not in record['limitations'] and len(record['limitations']) < MAX_ITEMS:
                record['limitations'].append(label)
    if record['tasks'] or record['files'] or record['checks']:
        record['extraction'] = 'PARTIAL'
    return record


def directory() -> Path:
    base = os.environ.get('LOCALAPPDATA')
    if not base or base.startswith(('\\\\', '//')) or not Path(base).is_absolute():
        raise ValueError('local-store-unavailable')
    target = Path(os.path.abspath(base)) / 'audio-masking-website' / 'session-summaries'
    # Reject a configured store in the repository, even via a junction/symlink.
    if target.is_relative_to(ROOT):
        raise ValueError('repository-store')
    current = Path(target.anchor)
    for part in target.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('unsafe-store')
    return target


def read_state(path: Path) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {'version': 1, 'records': [], 'record_limit_reached': False}
    if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('unsafe-state')
    with path.open('rb') as stream:
        raw = stream.read(MAX_STATE + 1)
    if len(raw) > MAX_STATE:
        raise ValueError('state-size')
    data = json.loads(raw)
    # Validate the store rather than copying arbitrary local text into summaries.
    if not isinstance(data, dict) or set(data) != {'version', 'records', 'record_limit_reached'} or data['version'] != 1 or type(data['record_limit_reached']) is not bool:
        raise ValueError('state-schema')
    if not isinstance(data['records'], list) or len(data['records']) > MAX_RECORDS:
        raise ValueError('records')
    for entry in data['records']:
        if not isinstance(entry, dict) or set(entry) != {'id', 'data'} or not re.fullmatch(r'[a-f0-9]{64}', entry.get('id', '')):
            raise ValueError('entry')
        record = entry['data']
        if not isinstance(record, dict) or set(record) != set(extract(None)):
            raise ValueError('record-schema')
        if record['source'] != extract(None)['source'] or record['extraction'] not in {'UNKNOWN', 'PARTIAL'}:
            raise ValueError('source')
        for key, labels in (('tasks', TASKS), ('checks', CHECKS)):
            if not isinstance(record[key], list) or len(record[key]) > MAX_ITEMS:
                raise ValueError('items')
            for item in record[key]:
                if not isinstance(item, dict) or set(item) != {'name', 'status'} or item['name'] not in labels or item['status'] not in STATUSES:
                    raise ValueError('item')
        if not isinstance(record['files'], list) or len(record['files']) > MAX_ITEMS or not all(isinstance(f, str) and safe_file(f) for f in record['files']):
            raise ValueError('files')
        allowed_limits = {'message-limit; remainder not inspected', 'sensitive-clause-omitted',
                          'heuristic analysis only', 'independent verification unavailable',
                          'component or verification unavailable', 'bounded inspection',
                          'real application not tested', 'real Codex session not tested'}
        if not isinstance(record['limitations'], list) or len(record['limitations']) > MAX_ITEMS or any(x not in allowed_limits for x in record['limitations']):
            raise ValueError('limitations')
    return data


def atomic_write(path: Path, value: dict, limit: int) -> None:
    raw = encode(value)
    if len(raw) > limit:
        raise ValueError('output-size')
    # Replace only our hashed state/summary; never follow a destination link.
    if path.is_symlink():
        raise ValueError('link')
    fd, temporary = tempfile.mkstemp(prefix='.summary-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def aggregate(state: dict) -> dict:
    groups = {s: {'tasks': [], 'checks': []} for s in STATUSES}
    files, limits = [], []
    for entry in state['records']:
        record = entry['data']
        for key in ('tasks', 'checks'):
            for item in record[key]:
                items = groups[item['status']][key]
                if item['name'] not in items:
                    items.append(item['name'])
        for value in record['files']:
            if value not in files and len(files) < 40:
                files.append(value)
        for value in record['limitations']:
            if value not in limits:
                limits.append(value)
    if not state['records'] or any(not e['data']['tasks'] for e in state['records']):
        groups['UNKNOWN']['tasks'].append('not reliably extracted')
    if not state['records'] or any(not e['data']['checks'] for e in state['records']):
        groups['UNKNOWN']['checks'].append('not reliably extracted')
    return {'version': 1, 'source': 'local Stop records; self-reported, not verified',
            'record_count': len(state['records']), 'record_limit_reached': state['record_limit_reached'],
            'statuses': groups, 'explicit_changed_files': files,
            'files_status': 'PARTIAL' if files else 'UNKNOWN',
            'limitations': limits, 'limitations_status': 'PARTIAL' if limits else 'UNKNOWN',
            'note': 'Missing information is UNKNOWN. Conflicting reports remain in separate status groups. No transcript was read.'}


def save(event: dict) -> str:
    kind = event.get('hook_event_name')
    if kind == 'Stop' and event.get('stop_hook_active'):
        return 'SKIPPED: stop_hook_active; no continuation or storage requested'
    session = event.get('session_id')
    if not isinstance(session, str) or not session.strip() or len(session) > 256:
        return 'UNKNOWN: session_id unavailable; nothing stored'
    key = hashlib.sha256(session.encode('utf-8')).hexdigest()
    target = directory()
    state_path = target / (key + '.records.json')
    lock = target / (key + '.lock')
    # No retries or waiting: a busy/stale lock reports UNKNOWN, never blocks Stop.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        state = read_state(state_path)
        if not state_path.exists() and not (target / (key + '.summary.json')).exists():
            sessions = set()
            with os.scandir(target) as entries:
                for index, entry in enumerate(entries):
                    match = re.fullmatch(r'([a-f0-9]{64})\.(?:records|summary)\.json', entry.name)
                    if match:
                        sessions.add(match[1])
                    if index > MAX_SESSIONS * 3 or len(sessions) >= MAX_SESSIONS:
                        return 'UNKNOWN: local session-store limit; nothing stored'
        if kind == 'Stop':
            record = extract(event.get('last_assistant_message'))
            fingerprint = hashlib.sha256(encode(record)).hexdigest()
            if any(e['id'] == fingerprint for e in state['records']):
                return 'SKIPPED: duplicate sanitized record'
            if len(state['records']) >= MAX_RECORDS:
                state['record_limit_reached'] = True
                atomic_write(state_path, state, MAX_STATE)
                return 'SKIPPED: record limit reached; later work not recorded'
            state['records'].append({'id': fingerprint, 'data': record})
            atomic_write(state_path, state, MAX_STATE)
            return 'RECORDED: short sanitized technical record; missing results remain UNKNOWN'
        atomic_write(target / (key + '.summary.json'), aggregate(state), MAX_SUMMARY)
        return 'RECORDED: session summary'
    finally:
        lock.unlink()


def main() -> None:
    event = None
    result = 'UNKNOWN: invalid event or local storage unavailable; nothing confirmed'
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('input-size')
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError('event')
        if event.get('hook_event_name') not in {'Stop', 'SessionEnd'}:
            return
        if event.get('hook_event_name') == 'Stop' and event.get('stop_hook_active'):
            return
        result = save(event)
    except Exception:
        pass  # No exception/payload/path details; always advisory, exit 0.
    if isinstance(event, dict) and event.get('hook_event_name') == 'SessionEnd':
        if result.startswith('UNKNOWN'):
            print('Session Summary: UNKNOWN; local summary could not be confirmed.', file=sys.stderr)
        return  # SessionEnd does not request a model response or emit hook JSON.
    print(json.dumps({'systemMessage': 'Session Summary: ' + result}, ensure_ascii=True))


if __name__ == '__main__':
    main()
