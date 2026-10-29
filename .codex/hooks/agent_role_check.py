"""Bounded role context and advisory final-message review, stdlib/Python 3.11.

Only three fixed local TOML profiles can be read. Transcript paths, cwd,
agent IDs and paths mentioned in messages are never opened or resolved.
Start: hookSpecificOutput.additionalContext supplies role context explicitly.
Stop: the common informational systemMessage field never blocks termination.
No decision, permissionDecision, stop, retry or transcript inspection is used.
Text findings are candidates, never proof of actions or authorization.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys
import tomllib


ROOT = Path(__file__).absolute().parents[2]
ROLES = frozenset({'frontend', 'backend', 'qa'})
MAX_INPUT = 1024 * 1024
MAX_PROFILE = 32768
MAX_MESSAGE = 32768
MAX_INSTRUCTIONS = 16000
BOUNDARIES = {
    'frontend': 'Работай над порученным frontend. Не меняй backend и API-контракты без отдельного поручения; несоответствия передавай координатору.',
    'backend': 'Работай над порученным backend через публичный контракт и отдельный адаптер. Не читай, не ищи, не копируй и не изменяй исходники закрытого алгоритма.',
    'qa': 'Проводь ревью и существующие безопасные проверки. Не исправляй основной код самостоятельно. Изменение тестов требует явного поручения.',
}
COMMON = ('Описание роли не разрешает начинать разработку сайта или расширять задачу. '
          'Соблюдай AGENTS.md и явно порученный объём работы. Не используй сеть, GitHub '
          'и пользовательские аудиозаписи в рамках этой проверки. Передай координатору '
          'результаты проверок и ограничения. Не делегируй работу без отдельного поручения.')


def output(event_name: str, message: str) -> dict:
    message = 'Agent Role Check: ' + message
    if event_name == 'SubagentStart':
        return {'hookSpecificOutput': {'hookEventName': 'SubagentStart',
                                      'additionalContext': message}}
    # Informational output, not SubagentStop's blocking decision/reason.
    return {'systemMessage': message}


def role_of(event: dict) -> str | None:
    value = event.get('agent_type')
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    # Exact explicit role names only: no guessing from task, ID or description.
    return value if value in ROLES else None


def profile(role: str) -> str:
    """Read only .codex/agents/<known role>.toml, rejecting links/junctions."""
    if role not in ROLES:
        raise ValueError()
    current = ROOT
    for part in ('.codex', 'agents', role + '.toml'):
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError()
    with current.open('rb') as stream:
        data = stream.read(MAX_PROFILE + 1)
    if len(data) > MAX_PROFILE:
        raise ValueError()
    config = tomllib.loads(data.decode('utf-8-sig'))
    if config.get('name') != role:
        raise ValueError()
    for field in ('description', 'developer_instructions'):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError()
    # Deliberately validate a small known schema; unfamiliar extensions require
    # human review instead of assuming Codex accepts them.
    allowed = {'name', 'description', 'developer_instructions', 'model',
               'model_reasoning_effort', 'sandbox_mode'}
    if set(config) - allowed:
        raise ValueError()
    for field in ('model', 'model_reasoning_effort', 'sandbox_mode'):
        if field in config and (not isinstance(config[field], str) or not config[field].strip()):
            raise ValueError()
    if ('model_reasoning_effort' in config and config['model_reasoning_effort'] not in
            {'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'}):
        raise ValueError()
    if ('sandbox_mode' in config and config['sandbox_mode'] not in
            {'read-only', 'workspace-write', 'danger-full-access'}):
        raise ValueError()
    instructions = config['developer_instructions'].strip()
    if len(instructions) > MAX_INSTRUCTIONS:
        raise ValueError()
    return instructions


def start(event: dict) -> dict:
    role = role_of(event)
    if role is None:
        return output('SubagentStart', 'UNKNOWN — agent_type не задаёт явно frontend, backend или qa. '
                      'Соответствие пользовательскому профилю не установлено; профили не читались.')
    try:
        instructions = profile(role)
    except (OSError, ValueError, UnicodeError):
        return output('SubagentStart', f'REVIEW — .codex/agents/{role}.toml недоступен, '
                      'некорректен, превышает лимит или содержит неподдерживаемую структуру. '
                      'Применение профиля не подтверждено. ' + BOUNDARIES[role] + ' ' + COMMON)
    return output('SubagentStart', f'ROLE_CONTEXT — явная роль {role}; локальный TOML '
                  'прошёл ограниченную проверку структуры. Hook передаёт инструкции ниже; '
                  'это не доказательство автоматического применения профиля движком Codex.\n'
                  + BOUNDARIES[role] + '\n' + COMMON + '\nИнструкции профиля:\n' + instructions)


ACTION = re.compile(r'(?i)\b(?:исправ\w*|измен\w*|отредактир\w*|перепис\w*|добав\w*|'
                    r'реализова\w*|обнов\w*|fix(?:ed)?|chang(?:e|ed)|edit(?:ed)?|'
                    r'modif(?:y|ied)|rewr(?:ote|itten)|implement(?:ed)?|updat(?:e|ed)|patch(?:ed)?)\b')
ACCESS = re.compile(r'(?i)\b(?:прочита\w*|чита\w*|изуч\w*|откр\w*|скопир\w*|'
                    r'запрос\w*|наш[её]л|искал|read|inspect(?:ed)?|open(?:ed)?|'
                    r'cop(?:y|ied)|access(?:ed)?|request(?:ed)?|search(?:ed)?)\b')
NEGATED = re.compile(r'(?i)(?:\bне|\bnot|\bnever|\bwithout|\bno)\s+(?:\w+\s+){0,2}$')


def affirmative(pattern: re.Pattern, clause: str) -> bool:
    for match in pattern.finditer(clause):
        prefix = clause[max(0, match.start() - 60):match.start()]
        if not NEGATED.search(prefix):
            return True
    return False


def risks(role: str, message: str) -> list[str]:
    found = set()
    # Bounded short clauses reduce accidental association across sentences.
    for clause in re.split(r'[\n;!?]|(?<=[а-яa-z])\.(?:\s|$)|,', message.lower()):
        for offset in range(0, len(clause), 400):
            text = clause[max(0, offset - 150):offset + 400]
            changed = affirmative(ACTION, text)
            if role == 'qa' and changed and re.search(
                    r'основн\w*\s+код|продуктов\w*\s+код|production|application\s+code|'
                    r'основн\w*\s+реализац|(?:backend|frontend|src)[/\\]|\bapp\.py\b', text):
                found.add('qa-main-code-edit: возможное самостоятельное исправление основного кода')
            if role == 'frontend' and changed and re.search(
                    r'\bbackend\b|\bfastapi\b|серверн\w*\s+(?:код|част|обработ)|'
                    r'api[- ]контракт|api\s+contract', text):
                found.add('frontend-backend-edit: возможное изменение backend; отдельное поручение не проверено')
            if role == 'backend' and (changed or affirmative(ACCESS, text)) and re.search(
                    r'закрыт\w*\s+алгоритм|(?:closed|private|proprietary)[ _-]+algorithm|'
                    r'algorithm[ _-]+(?:source|internals)', text):
                # An adapter/contract change alone is permitted; source access
                # or an explicit algorithm implementation change is suspicious.
                source = re.search(r'исходн|source|internals|реализац', text)
                interface = re.search(r'адаптер|adapter|контракт|contract', text)
                if source or not interface:
                    found.add('backend-private-algorithm: возможная работа с закрытой реализацией')
    return sorted(found)


def stop(event: dict) -> dict:
    role = role_of(event)
    if role is None:
        return output('SubagentStop', 'UNKNOWN — явная роль отсутствует или не распознана; '
                      'оценить границы Frontend/Backend/QA нельзя.')
    message = event.get('last_assistant_message')
    if not isinstance(message, str) or not message.strip():
        return output('SubagentStop', f'UNKNOWN — роль {role}; итоговое сообщение отсутствует '
                      'или имеет неподдерживаемый формат. Журнал не читался.')
    limited = len(message) > MAX_MESSAGE
    findings = risks(role, message[:MAX_MESSAGE])
    if findings:
        detail = '; '.join(findings) + '. Требуется проверка координатором.'
    else:
        detail = 'В доступном тексте явных признаков выхода за роль не найдено; '
        detail += 'итоговое сообщение не доказывает соблюдение роли. Данных для PASSED недостаточно.'
    if limited:
        detail += ' Сообщение превышает лимит; остаток не анализировался.'
    return output('SubagentStop', f'REVIEW — роль {role}. ' + detail +
                  ' Анализ эвристический; поручение, реальные изменения и согласование не проверены. '
                  'Остановка или повтор работы не запрашиваются.')


def record_probe_event(event: dict) -> None:
    """Optionally record only bounded lifecycle metadata; never affect the hook."""
    try:
        if os.environ.get('AUDIO_HARNESS_ROLE_PROBE') != '1':
            return
        kind = event.get('hook_event_name')
        if kind not in ('SubagentStart', 'SubagentStop'):
            return
        local_app_data = os.environ.get('LOCALAPPDATA')
        if not local_app_data:
            return
        directory = Path(local_app_data) / 'audio-masking-website' / 'hook-probes'
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'event': kind,
            'agent_type': role_of(event) or 'unknown',
        }
        with (directory / 'agent-role-events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=True) + '\n')
    except Exception:
        # Diagnostic failures must not change decisions, messages or termination.
        pass


def handle(event: dict) -> dict:
    kind = event.get('hook_event_name')
    if kind == 'SubagentStart':
        return start(event)
    if kind == 'SubagentStop':
        return stop(event)
    return {'systemMessage': 'Agent Role Check: UNKNOWN — неподдерживаемое событие; проверка не выполнена.'}


def main() -> None:
    event = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError()
        record_probe_event(event)
        result = handle(event)
    except Exception:
        # No raw payloads, assistant messages, paths or exception details.
        message = 'REVIEW — некорректное событие или локальная ошибка; проверка не завершена.'
        result = (output('SubagentStart', message)
                  if isinstance(event, dict) and event.get('hook_event_name') == 'SubagentStart'
                  else {'systemMessage': 'Agent Role Check: ' + message})
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
