"""Bounded advisory PostToolUse documentation review; no writes or commands.

Only public application trees, explicit changed files, README.md and docs/ are
eligible. OpenSpec is not user/developer documentation. Patch/Edit fragments
are preferred over whole-file keyword matches. No timestamps, keyword hits or
absence of hits prove that documentation agrees with runtime behavior.
"""

import ast
import json
import os
from pathlib import Path
import re
import stat
import sys
import time


ROOT = Path(__file__).absolute().parents[2]
MAX_INPUT = 1024 * 1024
MAX_BYTES = 65536
MAX_TOTAL = 512 * 1024
MAX_ENTRIES = 400
MAX_CHANGES = 20
MAX_DOCS = 12
SECONDS = 2
SOURCE = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.mts', '.cts', '.html', '.vue', '.svelte'}
CONFIG = {'.json', '.toml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.sh', '.ps1'}
TREES = {'backend', 'frontend', 'src', 'app'}
EXCLUDED = {'.git', '.codex', '.agents', 'openspec', 'node_modules', '.venv',
            'venv', '__pycache__', 'dist', 'build', 'coverage', 'private',
            'secrets', 'algorithm', 'algorithms', 'closed_algorithm',
            'masking_algorithm', 'private_algorithm', 'uploads', 'storage',
            'recordings', 'results', 'outputs', 'transcripts', 'tmp', 'temp'}
TOPICS = {
    'api': ('публичный API', re.compile(r'(?i)@\w+(?:\.\w+)*\.(?:get|post|put|patch|delete|route)\s*\(|\b(?:app|router)\.(?:get|post|put|patch|delete|use)\s*\(|\b(?:APIRouter|response_model|include_router)\b|\bexport\s+(?:async\s+)?(?:function|interface|type)\b'),
            re.compile(r'(?i)\bapi\b|endpoint|маршрут|эндпоинт')),
    'formats': ('поддерживаемые аудиоформаты', re.compile(r'(?i)\b(?:supported|allowed|accepted)[_\w]*(?:format|extension|mime)|\b(?:audio_formats|audio_extensions|audio_mime_types)\b|audio/(?:wav|mpeg|ogg|flac)|["\']\.(?:wav|mp3|flac|ogg|opus|m4a|aac)["\']'),
                re.compile(r'(?i)формат|format|\bwav\b|\bmp3\b|\bflac\b')),
    'processing': ('параметры обработки', re.compile(r'(?i)\b(?:sample_rate|sampling_rate|channels|bit_depth|max_upload\w*|max_file\w*|retention\w*|processing_timeout|masking_strength|masking_params)\b'),
                   re.compile(r'(?i)параметр|обработ|частот|хранен|лимит|processing|sample.rate|channels|retention|limit')),
    'features': ('пользовательские возможности', re.compile(r'(?i)\b(?:upload_audio|download_audio|mask_audio|unmask_audio|demask_audio|transcribe|transcription|calculate_pesq|calculate_visqol)\b|\b(?:pesq|visqol)\b|<button\b|\b(?:label|aria-label)\s*='),
                 re.compile(r'(?i)возможност|загруз|скача|маскиров|распознав|upload|download|mask|transcri|pesq|visqol')),
    'startup': ('инструкции по запуску', re.compile(r'(?i)\b(?:uvicorn|gunicorn|ffmpeg|npm run|pnpm run|yarn run|docker compose)\b|\b(?:process\.env|os\.environ|os\.getenv)\b|["\'](?:scripts|dependencies|devDependencies)["\']\s*:|^\s*(?:CMD|ENTRYPOINT|EXPOSE|FROM)\b'),
                re.compile(r'(?i)запуск|установ|настрой|окружени|start|setup|install|uvicorn|npm|docker|ffmpeg')),
}


class Budget:
    def __init__(self):
        self.deadline = time.monotonic() + SECONDS
        self.total = 0
        self.entries = 0

    def check(self):
        if time.monotonic() > self.deadline or self.total > MAX_TOTAL or self.entries > MAX_ENTRIES:
            raise ValueError('limit')


def permitted(path: Path) -> bool:
    try:
        parts = path.relative_to(ROOT).parts
        return bool(parts) and not any(
            part.lower() in EXCLUDED or Path(part).stem.lower() in EXCLUDED or part.lower().startswith('.env') or
            re.search(r'(?i)closed[_-]?algorithm|private[_-]?algorithm|masking[_-]?algorithm|credential|secret', part)
            for part in parts) and path.suffix.lower() not in {'.pem', '.key', '.pfx', '.p12'}
    except ValueError:
        return False


def info(path: Path):
    if not permitted(path):
        raise ValueError('excluded')
    current = ROOT
    for part in path.relative_to(ROOT).parts:
        current /= part
        result = current.lstat()
        if stat.S_ISLNK(result.st_mode) or getattr(result, 'st_file_attributes', 0) & 0x400:
            raise ValueError('link')
    return result


def read_text(path: Path, budget: Budget) -> str:
    budget.check()
    if not stat.S_ISREG(info(path).st_mode):
        raise ValueError('not-file')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    budget.total += len(data)
    budget.check()
    if len(data) > MAX_BYTES or b'\0' in data:
        raise ValueError('size-or-binary')
    return data.decode('utf-8-sig')


def walk(directory: Path, budget: Budget):
    """Bounded scandir, pruning excluded trees before accessing their entries."""
    if not stat.S_ISDIR(info(directory).st_mode):
        raise ValueError('not-directory')
    with os.scandir(directory) as entries:
        for entry in entries:
            budget.entries += 1
            budget.check()
            path = Path(entry.path)
            if not permitted(path):
                continue
            mode = info(path).st_mode
            if stat.S_ISDIR(mode):
                yield from walk(path, budget)
            elif stat.S_ISREG(mode):
                yield path


def site_exists(budget: Budget) -> bool:
    for name in ('main.py', 'app.py', 'index.html'):
        path = ROOT / name
        try:
            if stat.S_ISREG(info(path).st_mode):
                return True
        except FileNotFoundError:
            pass
    for name in sorted(TREES):
        try:
            for path in walk(ROOT / name, budget):
                if path.suffix.lower() in SOURCE and not is_test(path):
                    return True
        except FileNotFoundError:
            continue
    return False


def is_test(path: Path) -> bool:
    return ('tests' in path.parts or '__tests__' in path.parts or path.name.startswith('test_')
            or bool(re.search(r'(?:_test\.py|\.(?:test|spec)\.[cm]?[jt]sx?)$', path.name)))


def changes(event: dict) -> list[tuple[str, str | None, str | None]]:
    data = event.get('tool_input')
    if event['tool_name'] == 'apply_patch':
        patch = data if isinstance(data, str) else data.get('command', data.get('patch')) if isinstance(data, dict) else None
        if not isinstance(patch, str):
            raise ValueError('patch')
        result = []
        name, old, new = None, [], []
        for line in patch.splitlines():
            match = re.match(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', line)
            if match:
                if name is not None:
                    result.append((name, '\n'.join(old) if old or new else None,
                                   '\n'.join(new) if old or new else None))
                name, old, new = match[1], [], []
            elif name is not None and line.startswith(('+', '-')):
                (new if line.startswith('+') else old).append(line[1:])
        if name is not None:
            result.append((name, '\n'.join(old) if old or new else None,
                           '\n'.join(new) if old or new else None))
        if not result:
            raise ValueError('paths')
        return result
    if not isinstance(data, dict):
        raise ValueError('input')
    name = data.get('file_path', data.get('path'))
    if not isinstance(name, str) or not name:
        raise ValueError('path')
    old, new = data.get('old_string'), data.get('new_string')
    if event['tool_name'] == 'Write':
        old, new = None, data.get('content')
    return [(name, old if isinstance(old, str) else None, new if isinstance(new, str) else None)]


def cosmetic(old: str | None, new: str | None, suffix: str) -> bool:
    if old is None or new is None:
        return False
    if old == new:
        return True
    if suffix == '.py':
        try:
            return ast.dump(ast.parse(old)) == ast.dump(ast.parse(new))
        except (SyntaxError, ValueError, RecursionError):
            pass
    return False


def documents(budget: Budget) -> tuple[dict[str, str], list[str]]:
    result, notes = {}, []
    try:
        result['README.md'] = read_text(ROOT / 'README.md', budget)
    except FileNotFoundError:
        notes.append('README.md не найден')
    except (OSError, ValueError, UnicodeError):
        notes.append('README.md недоступен или превышает лимит')
    try:
        for path in walk(ROOT / 'docs', budget):
            if path.suffix.lower() not in {'.md', '.mdx', '.rst'}:
                continue
            if len(result) >= MAX_DOCS:
                notes.append('обзор docs/ ограничен количеством документов')
                break
            try:
                # Keep contents only in memory; no links are followed.
                result[path.relative_to(ROOT).as_posix()] = read_text(path, budget)
            except (OSError, ValueError, UnicodeError):
                notes.append('один из документов docs/ не удалось проверить')
    except FileNotFoundError:
        pass  # docs/ is optional; do not demand a new documentation subsystem.
    except (OSError, ValueError, RecursionError):
        notes.append('docs/ не удалось полностью проверить в пределах лимитов')
    return result, notes


def review(event: dict) -> str:
    budget = Budget()
    items = changes(event)
    cwd = event.get('cwd', str(ROOT))
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return 'UNKNOWN — некорректный cwd; файлы не проверены.'
    relevant, uncertain = [], []
    for name, old, new in items[:MAX_CHANGES]:
        budget.check()
        path = Path(os.path.abspath(os.path.join(cwd, name)))
        try:
            parts = path.relative_to(ROOT).parts
        except ValueError:
            uncertain.append('внешний путь исключён без обращения к нему')
            continue
        if not parts:
            uncertain.append('изменённый файл не определён')
            continue
        if parts[0].lower() in {'.codex', '.agents', 'docs', 'openspec'} or path.suffix.lower() in {'.md', '.mdx', '.rst', '.txt'}:
            continue
        if not permitted(path):
            uncertain.append('защищённый путь исключён; содержимое не читалось')
            continue
        if is_test(path):
            continue
        if path.suffix.lower() not in SOURCE | CONFIG and path.name.lower() not in {'dockerfile', 'makefile'}:
            uncertain.append('неподдерживаемый тип файла исключён без чтения')
            continue
        relevant.append((path, old, new))
    if len(items) > MAX_CHANGES:
        uncertain.append('превышен лимит изменённых файлов')
    if not relevant:
        return ('UNKNOWN — ' + '; '.join(uncertain) if uncertain else
                'SKIPPED — только документация, Harness, OpenSpec или тесты; исходники приложения не затронуты.')
    try:
        if not site_exists(budget):
            return 'SKIPPED — исходный код сайта ещё не создан в известных каталогах приложения.'
    except (OSError, ValueError, RecursionError):
        return 'UNKNOWN — наличие исходников приложения не установлено; путь недоступен или достигнут лимит.'
    topics = set()
    all_cosmetic = True
    for path, old, new in relevant:
        budget.check()
        try:
            # Validate changed file access even when event contains a fragment.
            mode = info(path).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError('not-file')
        except FileNotFoundError:
            if old is None or new is None:
                uncertain.append('удалённый файл без доступного фрагмента изменения')
                continue
        except (OSError, ValueError):
            uncertain.append('изменённый файл недоступен или является ссылкой')
            continue
        if cosmetic(old, new, path.suffix.lower()):
            continue
        all_cosmetic = False
        if new is None:
            try:
                new = read_text(path, budget)
            except (OSError, ValueError, UnicodeError):
                uncertain.append('содержимое изменённого файла не удалось проверить')
                continue
        fragment = (old or '') + '\n' + new
        if len(fragment) > MAX_BYTES:
            uncertain.append('фрагмент изменения превышает лимит')
            continue
        for topic, (_, signal, _) in TOPICS.items():
            if signal.search(fragment):
                topics.add(topic)
    if all_cosmetic and not uncertain:
        return 'SKIPPED — доступные изменения не меняют Python AST или содержимое; обновление документации не требуется этой проверкой.'
    if not topics:
        return 'UNKNOWN — явных признаков изменения публичного поведения не найдено. Обновление документации автоматически не требуется; по доступным данным соответствие не доказано.' + (' Проверка неполна: ' + '; '.join(uncertain) + '.' if uncertain else '')
    docs, notes = documents(budget)
    messages = []
    for topic in sorted(topics):
        title, _, marker = TOPICS[topic]
        related = [text for text in docs.values() if marker.search(text)]
        if not related:
            messages.append(title + ': соответствующее описание в README.md/docs не найдено')
        else:
            messages.append(title + ': тематическая документация найдена; проверьте её актуальность относительно изменения — совпадение слов её не доказывает')
    return ('REVIEW — возможное изменение внешнего поведения. ' + '; '.join(messages + notes + uncertain)
            + '. Это рекомендация для ручного сопоставления, а не требование менять документацию при каждом рефакторинге; устаревание автоматически не доказано.')


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('input-limit')
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError('event')
        if event.get('hook_event_name') != 'PostToolUse' or event.get('tool_name') not in {'apply_patch', 'Edit', 'Write'}:
            message = 'UNKNOWN — неподдерживаемое событие; проверка не выполнена.'
        else:
            message = review(event)
    except Exception:
        # Do not expose paths, snippets, transcripts, secrets or exceptions.
        message = 'UNKNOWN — некорректное событие, недоступные файлы или достигнут лимит; проверка не завершена.'
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',
          'additionalContext': 'Documentation Check: ' + message}}, ensure_ascii=True))


if __name__ == '__main__':
    main()
