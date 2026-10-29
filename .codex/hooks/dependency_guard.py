"""Advisory manifest review and lexical package-command policy, stdin only.

Never executes commands, reads project files, resolves paths or uses the network.
This is not a complete shell parser: aliases, generated commands, project scripts,
functions and indirect execution are outside its guarantees. No approval bypass.
Allowed commands emit nothing, retaining all other Codex approval requirements.
"""

import json
import re
import shlex
import sys


MAX_INPUT = 1024 * 1024
MAX_COMMAND = 65536
MAX_DEPTH = 5
MANAGERS = {
    'npm', 'npx', 'pnpm', 'yarn', 'pip', 'pip3', 'uv', 'uvx', 'poetry',
    'pipenv', 'bun', 'conda', 'mamba', 'micromamba', 'pdm', 'hatch',
    'pipx', 'easy_install', 'rye', 'cargo', 'rustup', 'go', 'gem',
    'bundle', 'bundler', 'composer', 'dotnet', 'nuget', 'apt', 'apt-get',
    'aptitude', 'apk', 'dnf', 'yum', 'pacman', 'brew', 'choco', 'winget',
    'scoop', 'corepack', 'deno', 'luarocks', 'Rscript', 'R',
}
MUTATIONS = {
    'install', 'i', 'in', 'ins', 'inst', 'insta', 'instal', 'ci', 'add',
    'update', 'upgrade', 'up', 'u', 'sync', 'download', 'fetch', 'get',
    'inject', 'reinstall', 'self-update', 'selfupdate', 'ensurepip',
    'require', 'restore', 'prepare', 'enable', 'use', 'setup', 'bootstrap',
    'dlx', 'create', 'exec', 'x', 'fix', 'lock', 'import', 'link',
}
SAFE = {
    'list', 'ls', 'll', 'la', 'show', 'info', 'view', 'outdated', 'tree',
    'why', 'explain', 'version', 'help', 'check', 'doctor', 'search',
    'test', 'lint', 'build', 'format', 'fmt', 'check-update', 'metadata',
    'freeze', 'debug', 'inspect', 'config', 'env', 'run', 'cache', 'audit',
    'validate', 'about', 'status', 'checkupdates',
}
VALUE_FLAGS = {'--prefix', '--userconfig', '--cache', '--registry', '--dir',
               '--directory', '--cwd', '-C', '--project', '--python', '-p',
               '--index-url', '--extra-index-url', '--config-file', '--root',
               '--globalconfig', '--workdir', '--working-dir', '-c'}
MANIFESTS = {
    'package.json', 'package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock',
    'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'bun.lock', 'bun.lockb',
    'pyproject.toml', 'poetry.lock', 'uv.lock', 'pipfile', 'pipfile.lock',
    'pdm.lock', 'setup.py', 'setup.cfg', 'environment.yml', 'environment.yaml',
    'cargo.toml', 'cargo.lock', 'go.mod', 'go.sum', 'gemfile', 'gemfile.lock',
    'composer.json', 'composer.lock', 'packages.config', 'packages.lock.json',
    'directory.packages.props', 'deno.json', 'deno.jsonc', 'deno.lock',
    '.npmrc', '.yarnrc', '.yarnrc.yml', '.python-version',
}


def deny(reason: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': 'Dependency Guard: ' + reason}}


def warn(message: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PostToolUse',
            'additionalContext': 'Dependency Guard: REVIEW — ' + message}}


def executable(token: str) -> str:
    name = token.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return re.sub(r'\.(?:exe|cmd|bat)$', '', name)


def substitutions(command: str) -> list[str]:
    """Inspect literal shell substitutions, but never single-quoted prose."""
    found = []
    quote = None
    i = 0
    while i < len(command):
        char = command[i]
        if char == '\\' and quote != "'":
            i += 2
            continue
        if char in "\"'" and (quote is None or quote == char):
            quote = None if quote else char
        elif quote != "'" and (command.startswith('$(', i) or char == '`'):
            backtick = char == '`'
            start = i + (1 if backtick else 2)
            end = start
            nesting = 1
            while end < len(command):
                if backtick and command[end] == '`':
                    break
                if not backtick:
                    if command[end] == '(':
                        nesting += 1
                    elif command[end] == ')':
                        nesting -= 1
                        if not nesting:
                            break
                end += 1
            if end == len(command):
                raise ValueError()
            found.append(command[start:end])
            i = end
        i += 1
    return found


def manager_reason(name: str, args: list[str], depth: int) -> str | None:
    if args and all(a in {'--version', '-V', '-v', '--help', '-h'} for a in args):
        return None
    if name in {'npx', 'uvx', 'easy_install', 'r', 'rscript'}:
        return 'вызов может загружать или устанавливать пакеты.'
    # Locate subcommand while skipping known global options and their values.
    index = 0
    while index < len(args) and args[index].startswith('-'):
        flag = args[index]
        index += 2 if flag in VALUE_FLAGS else 1
    rest = args[index:]
    if not rest:
        return 'неявная установка или неоднозначный вызов менеджера пакетов.'
    action = rest[0].lower()
    # These commands intentionally execute only existing project environments.
    if action == 'run':
        if name == 'uv' and '--no-sync' not in rest:
            return 'uv run может синхронизировать зависимости; нужен --no-sync.'
        if name in {'uv', 'poetry', 'pipenv', 'pdm', 'hatch', 'rye'}:
            command = rest[1:]
            while command and command[0].startswith('-'):
                flag = command.pop(0)
                if flag in VALUE_FLAGS and command:
                    command.pop(0)
            return segment_reason(command, depth + 1)
        return None
    if name == 'pnpm' and action == 'exec':
        return segment_reason(rest[1:], depth + 1)
    if name == 'go' and action in {'version', 'test', 'build', 'vet', 'list'}:
        return None
    if action in {'pip', 'tool', 'self', 'python', 'mod', 'global', 'env', 'cache', 'pkg', 'package', 'workspace', 'workspaces'}:
        # Inspect nested manager operations rather than accepting their parent.
        if any(a.lower() in MUTATIONS | {'set', 'create', 'remove', 'uninstall'} for a in rest[1:]):
            return 'вложенная операция меняет или загружает зависимости.'
        if action in {'pip', 'tool', 'self', 'python', 'mod', 'global', 'pkg', 'package'}:
            return manager_reason(name, rest[1:], depth + 1)
    if action == 'audit' and 'fix' in rest[1:]:
        return 'исправление audit меняет зависимости.'
    if action in MUTATIONS:
        return 'установка, добавление, обновление или загрузка зависимостей запрещены политикой.'
    if action in SAFE:
        return None
    return 'неизвестная операция менеджера пакетов; отсутствие установки не подтверждено.'


def segment_reason(tokens: list[str], depth: int) -> str | None:
    if depth > MAX_DEPTH:
        return 'превышен лимит вложенности; команда не проверена.'
    while tokens and (re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[0]) or tokens[0] in {'!', 'then', 'do', 'else'}):
        tokens = tokens[1:]
    if not tokens:
        return None
    name = executable(tokens[0])
    args = tokens[1:]
    if name in {'sudo', 'env', 'command', 'exec', 'nohup', 'time'}:
        while args and (args[0].startswith('-') or re.match(r'^\w+=', args[0])):
            flag = args.pop(0)
            if flag in {'-u', '--user', '-C', '--chdir'} and args:
                args.pop(0)
        return segment_reason(args, depth + 1)
    if name in {'bash', 'sh', 'zsh', 'dash', 'ksh', 'fish', 'cmd', 'powershell', 'pwsh'}:
        for i, arg in enumerate(args[:-1]):
            if arg.lower() in {'-c', '-lc', '-ic', '/c', '-command'}:
                return command_reason(args[i + 1], depth + 1)
    if name == 'eval':
        return command_reason(' '.join(args), depth + 1)
    if re.fullmatch(r'(?:python|pip)(?:\d+(?:\.\d+)*)?', name):
        if name.startswith('pip'):
            name = 'pip'
        elif '-m' in args:
            index = args.index('-m')
            if index + 1 < len(args):
                module = args[index + 1]
                if module == 'ensurepip':
                    return 'ensurepip устанавливает менеджер пакетов.'
                if module in MANAGERS:
                    name, args = module, args[index + 2:]
    if name in {m.lower() for m in MANAGERS}:
        return manager_reason(name, args, depth)
    return None


def command_reason(command: str, depth: int = 0) -> str | None:
    if depth > MAX_DEPTH or len(command) > MAX_COMMAND:
        return 'превышен лимит разбора; команда не проверена.'
    for nested in substitutions(command):
        reason = command_reason(nested, depth + 1)
        if reason:
            return reason
    lexer = shlex.shlex(command, posix=True, punctuation_chars=';|&()\n<>')
    lexer.whitespace = ' \t\r'
    lexer.commenters = '#'
    tokens = list(lexer)
    segment = []
    for token in tokens + [';']:
        if token and all(c in ';|&()\n' for c in token):
            reason = segment_reason(segment, depth)
            if reason:
                return reason
            segment = []
        elif token in {'<<', '<<<'}:
            # Do not interpret a documentation heredoc as executable commands.
            return 'heredoc требует ручной проверки; содержимое не интерпретируется как команды.'
        else:
            segment.append(token)
    return None


def dependency_file(name: str) -> bool:
    leaf = name.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return (leaf in MANIFESTS or leaf.endswith(('.csproj', '.fsproj', '.vbproj'))
            or bool(re.fullmatch(r'(?:requirements|constraints)(?:[-.][\w.-]+)?\.(?:txt|in)', leaf)))


def handle(event: dict) -> dict | None:
    kind = event.get('hook_event_name')
    data = event.get('tool_input')
    if kind == 'PreToolUse' and event.get('tool_name') == 'Bash':
        if not isinstance(data, dict) or not isinstance(data.get('command'), str):
            return deny('некорректное событие; команда не проверена.')
        try:
            reason = command_reason(data['command'])
        except (ValueError, RecursionError):
            reason = 'не удалось безопасно разобрать команду; требуется ручная проверка.'
        return deny(reason) if reason else None
    if kind == 'PostToolUse' and event.get('tool_name') in {'apply_patch', 'Edit', 'Write'}:
        if event['tool_name'] == 'apply_patch':
            patch = data if isinstance(data, str) else data.get('command', data.get('patch')) if isinstance(data, dict) else None
            names = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M) if isinstance(patch, str) else []
        else:
            name = data.get('file_path', data.get('path')) if isinstance(data, dict) else None
            names = [name] if isinstance(name, str) else []
        if not names:
            return warn('изменённые пути не определены; проверьте файлы зависимостей вручную.')
        if any(dependency_file(name) for name in names):
            return warn('изменён манифест или lock-файл зависимостей. Требуется явное согласование изменений; это событие не подтверждает согласие и не разрешает установку. Политика меняется только через доверенное управление Hooks.')
    return None


def main() -> None:
    event = None
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError()
        result = handle(event)
    except Exception:
        # Never echo commands, paths, payloads or exception details.
        result = (warn('проверка не завершена: некорректное событие.')
                  if isinstance(event, dict) and event.get('hook_event_name') == 'PostToolUse'
                  else deny('проверка не завершена: некорректное JSON-событие или локальная ошибка.'))
    if result is not None:
        print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
