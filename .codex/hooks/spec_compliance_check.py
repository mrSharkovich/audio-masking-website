"""Advisory, read-only OpenSpec review for PostToolUse apply_patch/Edit/Write.

Reads only local OpenSpec Markdown and selected YAML metadata, never source,
algorithm code or audio. Does not execute tools or validate code behavior.
The standard-library YAML inspection is intentionally shallow, not a YAML
parser or a substitute for OpenSpec validation. Built-in spec-driven Markdown
structure is checked; custom schemas always require manual review.
Path references and name matches are candidates, never compliance evidence.
"""

import json
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
EXCLUDED = {
    ".codex", ".agents", ".git", "docs", "node_modules", ".venv", "venv",
    "__pycache__", "dist", "build", "coverage", "private", "algorithm",
    "algorithms", "closed_algorithm", "recordings", "storage", "results",
}
MAX_BYTES = 131072
MAX_FILES = 300
MAX_COMPONENTS = 8
SECONDS = 4


def emit(message: str) -> None:
    if len(message) > 6000:
        message = message[:5900] + "\nОбзор сокращён; оставшиеся требования требуют ручной проверки."
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "Spec Compliance Check: " + message,
    }}, ensure_ascii=True))


def safe(path: Path) -> bool:
    try:
        parts = path.relative_to(ROOT).parts
        if ".." in parts or any(part.lower() in EXCLUDED for part in parts):
            return False
        if path.stem.lower() in {"algorithm", "closed_algorithm", "masking_algorithm"}:
            return False
        current = ROOT
        for part in parts:
            current /= part
            if current.is_symlink() or current.resolve() != current:
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def source_paths(event: dict) -> list[str]:
    data = event.get("tool_input")
    if not isinstance(data, dict):
        raise ValueError("нет объекта tool_input")
    if event["tool_name"] == "apply_patch":
        patch = data.get("command")
        if not isinstance(patch, str):
            raise ValueError("нет строки tool_input.command")
        names = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
        if not names:
            raise ValueError("не удалось определить изменённые файлы из патча")
    else:
        name = data.get("file_path", data.get("path"))
        if not isinstance(name, str):
            raise ValueError("нет пути изменённого файла")
        names = [name]
    cwd = Path(event.get("cwd", str(ROOT)))
    if not cwd.is_absolute():
        raise ValueError("cwd должен быть абсолютным")
    paths = set()
    for name in names:
        path = Path(name)
        path = path if path.is_absolute() else cwd / path
        if not safe(path):
            continue
        parts = path.relative_to(ROOT).parts
        if len(parts) < 2 or parts[0] not in {"backend", "frontend"}:
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if re.match(r"(?:vite|vitest|eslint|prettier)\.config\.", path.name):
            continue
        paths.add(path.relative_to(ROOT).as_posix())
    return sorted(paths)


def read_document(path: Path) -> str:
    """Never follow document links or read anything outside local OpenSpec."""
    if not safe(path) or not path.is_relative_to(ROOT / "openspec"):
        raise OSError("недоступный локальный документ")
    if path.suffix not in {".md", ".yaml"}:
        raise OSError("неподдерживаемый документ")
    with path.open("rb") as document:
        data = document.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("документ превышает лимит размера")
    return data.decode("utf-8-sig")


def plain_scalar(text: str, key: str) -> str | None:
    """Only unambiguous single-line top-level scalars; no YAML evaluation."""
    values = re.findall(r"^" + re.escape(key) + r":\s*([^\n]*)$", text, re.M)
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("повтор поля YAML " + key)
    value = values[0].strip()
    value = re.sub(r"\s+#.*$", "", value).strip()
    if re.fullmatch(r"[a-zA-Z0-9_./-]+", value):
        return value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        if re.fullmatch(r"[a-zA-Z0-9_./-]+", value[1:-1]):
            return value[1:-1]
    raise ValueError("поле YAML " + key + " требует полноценного разбора")


def unfenced(text: str) -> str:
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            mark = match[1][0]
            if fence is None:
                fence = mark
            elif fence == mark:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def structure(text: str, delta: bool) -> list[str]:
    """Check conventional requirement/scenario headings, not prose semantics."""
    text = unfenced(text)
    notes = []
    if not delta:
        for heading in ("Purpose", "Requirements"):
            if not re.search(r"^## " + heading + r"\s*$", text, re.M):
                notes.append("нет заголовка ## " + heading)
    elif not re.search(r"^## (?:ADDED|MODIFIED|REMOVED|RENAMED) Requirements\s*$", text, re.M):
        notes.append("нет раздела ADDED/MODIFIED/REMOVED/RENAMED Requirements")
    section = None
    requirement = None
    scenarios = 0
    count = 0
    def finish():
        if requirement is not None and scenarios == 0:
            notes.append("у требования нет #### Scenario: " + requirement[:60])
    for line in text.splitlines():
        if line.startswith("## "):
            finish()
            requirement = None
            section = line[3:].strip()
        elif line.startswith("### Requirement:"):
            finish()
            count += 1
            name = line.partition(":")[2].strip()
            if not name:
                notes.append("пустое имя Requirement")
            if not delta or section in {"ADDED Requirements", "MODIFIED Requirements"}:
                requirement, scenarios = name, 0
            else:
                requirement = None
        elif re.match(r"^#### Scenario:\s*\S", line) and requirement is not None:
            scenarios += 1
    finish()
    rename_only = delta and re.search(r"^## RENAMED Requirements\s*$", text, re.M)
    if not count and not rename_only:
        notes.append("нет ### Requirement:")
    if rename_only and not count and not (re.search(r"^\s*- FROM:", text, re.M) and re.search(r"^\s*- TO:", text, re.M)):
        notes.append("RENAMED: нет пар FROM/TO")
    return list(dict.fromkeys(notes))


def discover(deadline: float) -> tuple[dict[Path, str], list[str], list[str], str, bool]:
    documents = {}
    notes = []
    changes = []
    schema = "spec-driven"
    config = ROOT / "openspec/config.yaml"
    if config.exists():
        try:
            text = read_document(config)
            schema = plain_scalar(text, "schema") or schema
            if re.search(r"^store\s*:", text, re.M):
                notes.append("config.yaml задаёт store; внешнее хранилище не читается")
            notes.append("config.yaml учтён; полная корректность YAML и rules/context автоматически не проверяется")
        except (OSError, ValueError, UnicodeError):
            schema = "unknown"
            notes.append("config.yaml не удалось однозначно прочитать; схема требует REVIEW")
    count = 0
    limited = False
    for tree in ("specs", "changes"):
        directory = ROOT / "openspec" / tree
        if not safe(directory):
            notes.append(f"openspec/{tree}: путь исключён (внешний/символическая ссылка)")
            limited = True
            continue
        if not directory.exists():
            continue
        if not directory.is_dir():
            notes.append(f"openspec/{tree} существует, но не является каталогом")
            continue
        if tree == "changes":
            for child in sorted(directory.iterdir()):
                if safe(child) and child.is_dir() and child.name != "archive" and not child.name.startswith("."):
                    changes.append(child.name)
        for base, dirs, names in os.walk(directory, followlinks=False):
            count += 1
            parent = Path(base)
            dirs[:] = sorted(name for name in dirs if safe(parent / name) and
                             not name.startswith(".") and not (parent == directory and tree == "changes" and name == "archive"))
            for name in sorted(names):
                count += 1
                if count > MAX_FILES or time.monotonic() > deadline:
                    limited = True
                    break
                path = parent / name
                if not safe(path):
                    continue
                if name == "spec.md" or (tree == "changes" and name in {"proposal.md", "design.md", "tasks.md", ".openspec.yaml"}):
                    try:
                        documents[path] = read_document(path)
                    except (OSError, ValueError, UnicodeError):
                        notes.append(f"{path.relative_to(ROOT).as_posix()}: чтение пропущено")
                        limited = True
            if limited:
                break
    return documents, notes, changes, schema, limited


def review(paths: list[str]) -> str:
    if not paths:
        return "SKIPPED — нет изменений исходников backend/frontend; документация, OpenSpec и конфигурации Harness не требуют спецификации."
    documents, notes, changes, schema, limited = discover(time.monotonic() + SECONDS)
    specs = {path: text for path, text in documents.items() if path.name == "spec.md"}
    problems = []
    if schema == "spec-driven":
        for path, text in specs.items():
            relative = path.relative_to(ROOT / "openspec")
            delta = relative.parts[0] == "changes"
            metadata = ROOT / "openspec/changes" / relative.parts[1] / ".openspec.yaml" if delta else None
            if metadata in documents:
                try:
                    change_schema = plain_scalar(documents[metadata], "schema") or schema
                    skip_specs = plain_scalar(documents[metadata], "skip_specs")
                except ValueError:
                    notes.append(f"{metadata.relative_to(ROOT)}: метаданные требуют ручного разбора")
                    continue
                if skip_specs == "true":
                    problems.append(f"{path.relative_to(ROOT)}: spec.md существует при skip_specs: true")
                if change_schema != "spec-driven":
                    notes.append(f"{path.relative_to(ROOT)}: пользовательская схема {change_schema}; структура не проверялась")
                    continue
            expected = len(relative.parts) >= (5 if delta else 3)
            if delta:
                expected &= relative.parts[2] == "specs"
            if not expected:
                problems.append(f"{path.relative_to(ROOT).as_posix()}: неожиданный путь spec.md")
            problems.extend(f"{path.relative_to(ROOT).as_posix()}: {note}" for note in structure(text, delta))
    else:
        notes.append(f"схема {schema}: структура артефактов требует ручной проверки")
    if changes:
        notes.append("активные каталоги changes (готовность не подтверждена): " + ", ".join(changes[:4]))
    if not specs:
        status = "REVIEW" if limited or schema == "unknown" else "SKIPPED"
        return status + " — локальные spec.md с требованиями не найдены; соответствие кода не проверено. " + "; ".join(notes[:5])
    messages = []
    for path in paths[:MAX_COMPONENTS]:
        reference = re.compile(r"(?<![\w./-])" + re.escape(path) + r"(?![\w./-])")
        explicit = [doc.relative_to(ROOT).as_posix() for doc, text in documents.items() if reference.search(text)]
        keywords = set(re.findall(r"[a-z0-9]+", Path(path).stem.lower())) - {"app", "main", "index", "test", "init"}
        candidates = [doc.relative_to(ROOT).as_posix() for doc in specs if keywords and
                      keywords & set(re.findall(r"[a-z0-9]+", doc.parent.name.lower()))]
        if explicit:
            messages.append(f"{path}: явная текстовая ссылка в " + ", ".join(explicit[:3]) + "; это не доказательство соответствия.")
        elif candidates:
            messages.append(f"{path}: кандидаты по именам — " + ", ".join(candidates[:3]) + "; связь с требованиями не установлена.")
        else:
            messages.append(f"{path}: связанная спецификация/активное изменение не установлены; сопоставьте изменение с конкретными требованиями вручную.")
    if problems:
        messages.append("Наблюдаемые проблемы структуры spec-driven: " + "; ".join(problems[:5]))
    if limited or len(paths) > MAX_COMPONENTS:
        notes.append("обзор ограничен размером/временем; отсутствие связи не окончательно")
    return "REVIEW — " + "\n".join(messages + notes[:4] + [
        "Поведение кода и выполнение требований из свободного текста автоматически не установлены; нужна ручная проверка."
    ])


def main() -> None:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("ожидается JSON-объект")
        if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") not in {"apply_patch", "Edit", "Write"}:
            return
        emit(review(source_paths(event)))
    except (ValueError, TypeError, OSError, RuntimeError):
        emit("REVIEW — недостаточно данных события или документы недоступны; соответствие автоматически не установлено.")


if __name__ == "__main__":
    main()
