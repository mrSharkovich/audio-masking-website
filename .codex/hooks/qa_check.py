"""Read-only, heuristic QA advice for PostToolUse apply_patch/Edit/Write.

Only public backend/frontend source and conventional test files are inspected.
No imports of project code, syntax checks, subprocesses, test execution, network,
coverage claims or writes. Test association and scenario hints use names, not
coverage data: REVIEW never means tests passed or behavior was verified.
Closed algorithm code belongs outside this repository; external paths, links,
private/algorithm trees, and audio files are never opened by this hook.
"""

import json
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
EXCLUDED = {
    ".codex", ".agents", ".git", "docs", "openspec", "node_modules", ".venv",
    "venv", "__pycache__", ".pytest_cache", ".vite", "dist", "build", "coverage",
    "private", "algorithm", "algorithms", "closed_algorithm", "recordings",
    "storage", "results",
}
PRIVATE_STEMS = {"algorithm", "closed_algorithm", "masking_algorithm", "private_algorithm"}
MAX_BYTES = 131072
MAX_FILES = 5000
MAX_COMPONENTS = 8
SECONDS = 4
FEATURES = (
    ({"upload", "uploads", "uploader"}, "загрузка", "повреждённый/пустой файл, неподдерживаемый формат, превышение лимита"),
    ({"convert", "conversion", "converter", "ffmpeg"}, "конвертация", "ошибка/недоступность FFmpeg, некорректный вход, очистка временных файлов"),
    ({"mask", "masking"}, "маскирование", "недоступность адаптера, ошибка обработки; тестовая заглушка вместо закрытого алгоритма"),
    ({"demask", "demasking", "unmask", "unmasking"}, "демаскирование", "ошибка/недоступность адаптера и некорректный вход по согласованному контракту"),
    ({"pesq"}, "PESQ", "недоступная зависимость, несовместимые WAV и ошибка расчёта без вымышленных значений"),
    ({"visqol"}, "ViSQOL", "недоступная зависимость, несовместимые WAV и ошибка расчёта без вымышленных значений"),
    ({"llm", "transcribe", "transcription", "transcriber"}, "транскрибация", "недоступность локальной модели и ошибка распознавания; без внешних вызовов"),
)


def emit(message: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": "QA Check: " + message,
    }}, ensure_ascii=True))


def safe(path: Path) -> bool:
    try:
        relative = path.relative_to(ROOT)
        if ".." in relative.parts or path.stem.lower() in PRIVATE_STEMS:
            return False
        if any(part.lower() in EXCLUDED for part in relative.parts):
            return False
        current = ROOT
        for part in relative.parts:
            current /= part
            if current.is_symlink() or current.resolve() != current:
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def is_source(path: Path) -> bool:
    if not safe(path):
        return False
    parts = path.relative_to(ROOT).parts
    if len(parts) < 2:
        return False
    if parts[0] == "backend":
        return path.suffix.lower() == ".py"
    if parts[0] == "frontend" and path.suffix.lower() in FRONTEND:
        return not re.match(r"(?:vite|vitest|eslint|prettier)\.config\.", path.name)
    return False


def is_test(path: Path) -> bool:
    if path.suffix.lower() == ".py":
        return path.name.startswith("test_") or path.name.endswith("_test.py")
    return bool(re.search(r"\.(test|spec)\.[cm]?[jt]sx?$", path.name) or
                "__tests__" in path.parts)


def changed_paths(event: dict) -> list[Path]:
    data = event.get("tool_input")
    if not isinstance(data, dict):
        raise ValueError("tool_input")
    if event["tool_name"] == "apply_patch":
        command = data.get("command")
        if not isinstance(command, str):
            raise ValueError("command")
        names = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", command, re.M)
    else:
        name = data.get("file_path", data.get("path"))
        if not isinstance(name, str):
            raise ValueError("file_path")
        names = [name]
    cwd = Path(event.get("cwd", str(ROOT)))
    if not cwd.is_absolute():
        raise ValueError("cwd")
    paths = set()
    for name in names:
        path = Path(name)
        path = path if path.is_absolute() else cwd / path
        if is_source(path):
            paths.add(path)
    return sorted(paths)


def inventory(suite: str, deadline: float) -> tuple[list[Path], bool]:
    files = []
    visited = 0
    for base, dirs, names in os.walk(ROOT / suite, followlinks=False):
        parent = Path(base)
        dirs[:] = sorted(name for name in dirs if safe(parent / name))
        for name in sorted(names):
            visited += 1
            if visited > MAX_FILES or time.monotonic() > deadline:
                return files, True
            path = parent / name
            if is_source(path) and path.is_file():
                files.append(path)
    return files, False


def read_source(path: Path) -> str:
    if not is_source(path) or not path.is_file():
        raise OSError("not a public source file")
    with path.open("rb") as source:
        content = source.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError("source too large")
    return content.decode("utf-8-sig", errors="replace")


def tokens(name: str) -> set[str]:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def component_tokens(path: Path) -> set[str]:
    return tokens(path.stem) - {"test", "tests", "spec", "use", "index", "init", "app", "main"}


def related_tests(path: Path, tests: list[Path]) -> list[Path]:
    def module_name(file: Path) -> str:
        stem = re.sub(r"^test_|(?:_test|\.(?:test|spec))$", "", file.stem)
        return re.sub(r"[^a-z0-9]", "", stem.lower())

    key = component_tokens(path)
    name = module_name(path)
    return [test for test in tests if test == path or
            (name and name == module_name(test)) or (key and key <= component_tokens(test))]


def feature_hints(path: Path, text: str) -> list[str]:
    # Be conservative around explicit placeholders: do not suggest a feature
    # already exists just because its stub or an interface declares a name.
    if is_test(path) or re.search(r"NotImplemented|\bTODO\b|(?:^|\s)(?:pass|\.\.\.)\s*$", text, re.M):
        return []
    declared = re.findall(r"^\s*(?:(?:export|default|async)\s+)*(?:def|class|function|const|let)\s+(\w+)", text, re.M)
    if not declared:
        return []
    identifiers = tokens(path.stem + "_" + "_".join(declared))
    return [f"{label}: проверьте негативные сценарии — {scenarios}."
            for aliases, label, scenarios in FEATURES if identifiers & aliases]


def review(paths: list[Path]) -> str:
    if not paths:
        return "SKIPPED — нет изменений исходников backend/frontend; документация, Harness и OpenSpec исключены."
    deadline = time.monotonic() + SECONDS
    inventories = {}
    limited = len(paths) > MAX_COMPONENTS
    for suite in sorted({path.relative_to(ROOT).parts[0] for path in paths}):
        files, truncated = inventory(suite, deadline)
        inventories[suite] = files
        limited |= truncated
    messages = []
    hints = set()
    for path in paths[:MAX_COMPONENTS]:
        if time.monotonic() > deadline:
            limited = True
            break
        label = path.relative_to(ROOT).as_posix()
        suite = path.relative_to(ROOT).parts[0]
        files = inventories[suite]
        if not any(not is_test(file) and file.name not in {"__init__.py", "conftest.py"} for file in files):
            messages.append(f"{suite}: SKIPPED — реализация приложения не найдена.")
            continue
        if is_test(path):
            messages.append(f"{label}: изменён тест; проверьте соответствие проверок поведению и контрактам.")
            continue
        matches = related_tests(path, [file for file in files if is_test(file)])
        if matches:
            names = ", ".join(test.relative_to(ROOT).as_posix() for test in matches[:3])
            messages.append(f"{label}: возможные связанные тесты по именам — {names}.")
        else:
            messages.append(f"{label}: связанных тестов по именам не найдено; проверьте связь через импорты и добавьте проверки поведения, если их нет.")
        if not path.is_file():
            messages.append(f"{label}: файл удалён/перенесён; проверьте потребителей и актуальность тестов.")
            continue
        try:
            hints.update(feature_hints(path, read_source(path)))
        except (OSError, ValueError):
            messages.append(f"{label}: чтение пропущено; нужен ручной QA содержания.")
        if suite == "frontend":
            hints.add("Frontend: проверьте затронутые действия и состояния ошибки/ожидания, доступность, ПК и смартфон.")
        else:
            hints.add("Backend: проверьте успешный сценарий, валидацию входа, ошибки и безопасный контракт ответа.")
    if not messages:
        messages.append("SKIPPED — обзор не выполнен в пределах лимита.")
    only_skipped = all(": SKIPPED" in message or message.startswith("SKIPPED") for message in messages)
    if limited:
        messages.append("Обзор ограничен размером/временем; оставшиеся компоненты требуют ручного QA.")
    if only_skipped:
        return "SKIPPED — " + "\n".join(dict.fromkeys(messages))
    return "REVIEW — статические рекомендации, не результат тестирования.\n" + "\n".join(
        messages + sorted(hints) + ["Связь по именам эвристическая. Наличие тестов не доказывает покрытие; тесты и синтаксис здесь не проверялись."])


def main() -> None:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("event")
        if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") not in {"apply_patch", "Edit", "Write"}:
            return
        emit(review(changed_paths(event)))
    except (ValueError, TypeError, OSError, RuntimeError):
        emit("SKIPPED — некорректное событие или недоступные файлы; нужен ручной QA.")


if __name__ == "__main__":
    main()
