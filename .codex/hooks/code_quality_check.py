"""Advisory PostToolUse checks for apply_patch (Edit/Write aliases).

No installs, fixes, Python execution or bytecode files. Only paths explicitly
named by the edit are considered; external paths and symlinks are excluded.
ESLint checks edited files; tsc checks the nearest configured project. Local
frontend tools and their configurations must be trusted: they execute code.
This hook cannot undo edits or observe edits made through other tool paths.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
EXCLUDED = {".codex", ".agents", ".git", "node_modules", ".venv", "venv", "docs", "openspec"}
ESLINT_CONFIGS = (
    "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
    "eslint.config.ts", "eslint.config.mts", "eslint.config.cts",
    ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs",
    ".eslintrc.yaml", ".eslintrc.yml",
)


def feedback(messages: list[str]) -> None:
    if messages:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "Code Quality Check:\n" + "\n".join(messages)[:6000],
        }}, ensure_ascii=True))


def local_path(path: Path) -> bool:
    """Reject escapes and symlinks/junctions before reading source files."""
    try:
        relative = path.relative_to(ROOT)
        if any(part.lower() in EXCLUDED for part in relative.parts):
            return False
        current = ROOT
        for part in relative.parts:
            current /= part
            if current.is_symlink() or current.resolve() != current:
                return False
        return path.resolve().is_relative_to(ROOT)
    except (OSError, ValueError, RuntimeError):
        return False


def changed_paths(event: dict) -> list[Path]:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("неподдерживаемый tool_input")
    if event["tool_name"] == "apply_patch":
        command = tool_input.get("command")
        if not isinstance(command, str):
            raise ValueError("нет строки патча tool_input.command")
        names = []
        # Deleted files have no remaining source to check. Moves use destination.
        for line in command.splitlines():
            match = re.fullmatch(r"\*\*\* (Add File|Update File|Move to): (.+)", line)
            if match:
                if match[1] == "Move to" and names:
                    names.pop()
                names.append(match[2])
    else:
        name = tool_input.get("file_path", tool_input.get("path"))
        if not isinstance(name, str):
            raise ValueError("нет пути изменённого файла")
        names = [name]
    cwd = Path(event.get("cwd", str(ROOT)))
    if not cwd.is_absolute():
        raise ValueError("cwd должен быть абсолютным")
    paths = []
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = cwd / path
        # Do not resolve symlinks away before local_path checks them.
        if ".." in path.parts:
            continue
        if local_path(path) and path.suffix.lower() in SOURCE_SUFFIXES:
            if path not in paths:
                paths.append(path)
    return paths


def parents_in_repo(path: Path):
    current = path.parent
    while current.is_relative_to(ROOT):
        yield current
        if current == ROOT:
            break
        current = current.parent


def find_config(path: Path, names: tuple[str, ...]) -> Path | None:
    for directory in parents_in_repo(path):
        for name in names:
            candidate = directory / name
            if local_path(candidate) and candidate.is_file():
                return candidate
    return None


def find_tool(directory: Path, relative: str) -> Path | None:
    for parent in (directory, *directory.parents):
        if not parent.is_relative_to(ROOT):
            break
        candidate = parent / "node_modules" / relative
        # node_modules is intentionally excluded from source checks, but the
        # executable must still resolve within the repository.
        if candidate.resolve().is_relative_to(ROOT) and candidate.is_file():
            return candidate
    return None


def run_check(label: str, args: list[str], cwd: Path, deadline: float) -> str:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return f"{label}: проверка пропущена — исчерпан лимит времени."
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=min(15, remaining),
                                shell=False)
    except subprocess.TimeoutExpired:
        return f"{label}: проверка не завершена — превышен лимит времени."
    except OSError:
        return f"{label}: проверка пропущена — инструмент не удалось запустить."
    if result.returncode:
        diagnostic = (result.stdout + "\n" + result.stderr).strip()[:1200]
        return f"{label}: ошибка (код {result.returncode}). {diagnostic}"
    return f"{label}: успешно."


def check(paths: list[Path]) -> list[str]:
    messages = []
    deadline = time.monotonic() + 45
    frontend = []
    for path in paths:
        label = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            messages.append(f"{label}: проверка пропущена — файл отсутствует.")
        elif path.suffix.lower() == ".py":
            try:
                compile(path.read_bytes(), label, "exec", dont_inherit=True)
                messages.append(f"Python {label}: синтаксис корректен.")
            except SyntaxError as error:
                messages.append(f"Python {label}:{error.lineno}:{error.offset}: {error.msg}.")
            except (OSError, ValueError, UnicodeError):
                messages.append(f"Python {label}: проверка не выполнена — ошибка чтения/компиляции.")
        else:
            frontend.append(path)
    checked_projects = set()
    node = shutil.which("node")
    for path in frontend:
        label = path.relative_to(ROOT).as_posix()
        config = find_config(path, ESLINT_CONFIGS)
        # Legacy package.json eslintConfig is also an explicit configuration.
        if config is None:
            package = find_config(path, ("package.json",))
            if package:
                try:
                    if "eslintConfig" in json.loads(package.read_text(encoding="utf-8-sig")):
                        config = package
                except (ValueError, OSError):
                    pass
        tool = find_tool(config.parent, "eslint/bin/eslint.js") if config else None
        if node and config and tool:
            messages.append(run_check(f"ESLint {label}",
                                      [node, str(tool), "--no-cache", "--no-fix", str(path)],
                                      config.parent, deadline))
        else:
            messages.append(f"ESLint {label}: проверка пропущена — нет Node.js, локального ESLint или конфигурации.")
        if path.suffix.lower() not in {".ts", ".tsx", ".mts", ".cts"}:
            continue
        config = find_config(path, ("tsconfig.json",))
        project = config or path.parent
        if project in checked_projects:
            continue
        checked_projects.add(project)
        tool = find_tool(config.parent, "typescript/bin/tsc") if config else None
        if node and config and tool:
            messages.append(run_check(f"TypeScript {config.relative_to(ROOT)}",
                                      [node, str(tool), "--noEmit", "--incremental", "false",
                                       "--project", str(config)], config.parent, deadline))
        else:
            messages.append(f"TypeScript {label}: проверка пропущена — нет Node.js, локального TypeScript или tsconfig.json.")
    return messages


def main() -> None:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("ожидается JSON-объект")
        if event.get("hook_event_name") != "PostToolUse":
            return
        if event.get("tool_name") not in {"apply_patch", "Edit", "Write"}:
            return
        feedback(check(changed_paths(event)))
    except (ValueError, OSError, RuntimeError) as error:
        feedback([f"проверка пропущена — некорректное событие или недоступный путь ({type(error).__name__})."])


if __name__ == "__main__":
    main()
