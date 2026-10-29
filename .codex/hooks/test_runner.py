"""Advisory PostToolUse runner for existing backend/pytest and frontend/Vitest.

Only backend/ and frontend/ source edits trigger suites. No shell, package
scripts, installs, fixes or external source discovery. Tests/configs are trusted
project code, not sandboxed here; they must obey the project's local-only,
synthetic-audio/stub policy. This is not a guard against arbitrary test code.
Runtime deduplication state lives in the OS temp directory, never in the repo.
Only apply_patch and its Edit/Write aliases are covered; edits cannot be undone.
"""

import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib


ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 20
EXCLUDED = {
    ".codex", ".agents", ".git", "openspec", "docs", "node_modules",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".vite", "coverage",
    "dist", "build", "private", "algorithm", "algorithms", "closed_algorithm",
    "audio", "uploads", "recordings", "storage", "results",
}
FRONTEND = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
HASH_SUFFIXES = FRONTEND | {".py", ".json", ".toml", ".ini", ".cfg", ".yaml", ".yml", ".txt", ".lock"}


def emit(messages: list[str]) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "Test Runner: " + "\n".join(messages),
    }}, ensure_ascii=True))


def safe(path: Path, dependencies: bool = False) -> bool:
    """Check lexical containment and reject symlinks/junctions before reads."""
    try:
        relative = path.relative_to(ROOT)
        if ".." in relative.parts:
            return False
        excluded = EXCLUDED - {"node_modules", ".venv", "venv"} if dependencies else EXCLUDED
        if any(part.lower() in excluded for part in relative.parts):
            return False
        current = ROOT
        for part in relative.parts:
            current /= part
            if current.is_symlink() or current.resolve() != current:
                return False
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def affected(event: dict) -> set[str]:
    data = event.get("tool_input")
    if not isinstance(data, dict):
        raise ValueError("tool_input")
    if event["tool_name"] == "apply_patch":
        patch = data.get("command")
        if not isinstance(patch, str):
            raise ValueError("command")
        # Include both old and new paths for moves and deleted source files.
        names = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
    else:
        name = data.get("file_path", data.get("path"))
        if not isinstance(name, str):
            raise ValueError("file_path")
        names = [name]
    cwd = Path(event.get("cwd", str(ROOT)))
    if not cwd.is_absolute():
        raise ValueError("cwd")
    suites = set()
    for name in names:
        path = Path(name)
        path = path if path.is_absolute() else cwd / path
        if not safe(path):
            continue
        parts = path.relative_to(ROOT).parts
        if len(parts) < 2:
            continue
        suite = parts[0]
        if suite == "backend" and path.suffix.lower() == ".py":
            suites.add(suite)
        elif suite == "frontend" and path.suffix.lower() in FRONTEND:
            if not re.match(r"(?:vite|vitest|eslint|prettier)\.config\.", path.name):
                suites.add(suite)
    return suites


def inventory(directory: Path) -> list[Path]:
    """Walk only the selected public source tree; never read audio contents."""
    files = []
    for base, dirs, names in os.walk(directory, followlinks=False):
        parent = Path(base)
        dirs[:] = sorted(name for name in dirs if safe(parent / name))
        for name in sorted(names):
            path = parent / name
            if path.suffix.lower() in HASH_SUFFIXES and safe(path):
                files.append(path)
        if len(files) > 10000:
            raise ValueError("source tree too large")
    return sorted(files)


def pytest_config(directory: Path) -> Path | None:
    for parent in (directory, ROOT):
        for name in ("pytest.ini", ".pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"):
            path = parent / name
            if not safe(path) or not path.is_file():
                continue
            if name.endswith(".ini") and name != "tox.ini":
                return path
            text = path.read_text(encoding="utf-8-sig")
            if name == "pyproject.toml":
                if "ini_options" in tomllib.loads(text).get("tool", {}).get("pytest", {}):
                    return path
            else:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(text)
                if parser.has_section("tool:pytest" if name == "setup.cfg" else "pytest"):
                    return path
    return None


def vitest_config(directory: Path) -> Path | None:
    for prefix in ("vitest", "vite"):
        for suffix in ("ts", "mts", "cts", "js", "mjs", "cjs"):
            path = directory / f"{prefix}.config.{suffix}"
            if safe(path) and path.is_file():
                if prefix == "vitest" or re.search(r"\btest\s*:", path.read_text(encoding="utf-8-sig")):
                    return path
    return None


def execute(args: list[str], directory: Path, timeout: float) -> tuple[int | None, str]:
    """Kill the owned process tree on timeout; never interpret event commands."""
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", CI="1")
    # Ambient CLI options must not add targets, watch mode or snapshot updates.
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(args, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, shell=False,
                                       start_new_session=os.name != "nt")
        except OSError:
            return None, "unavailable"
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    subprocess.run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"),
                                    "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, shell=False)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (OSError, subprocess.TimeoutExpired):
                pass  # Still terminate and reap the direct child below.
            process.kill()
            process.wait(timeout=5)
            return None, "timeout"
        output.seek(0)
        # Inspect only the standard no-tests marker, never return test output
        # that could contain application data or sensitive fixture contents.
        no_tests = b"no test files found" in output.read(65536).lower()
        return code, "no-tests" if no_tests else "completed"


def plan(suite: str, files: list[Path]) -> tuple[list[str], list[Path], str]:
    directory = ROOT / suite
    if suite == "backend":
        tests = directory / "tests"
        if not any(path.is_relative_to(tests) and
                   (path.name.startswith("test_") or path.name.endswith("_test.py")) and
                   path.suffix == ".py" for path in files):
            return [], [], "нет существующих тестов backend/tests"
        config = pytest_config(directory)
        if config is None:
            return [], [], "нет конфигурации pytest"
        interpreters = [directory / ".venv/Scripts/python.exe", directory / ".venv/bin/python",
                        ROOT / ".venv/Scripts/python.exe", ROOT / ".venv/bin/python"]
        python = next((str(path) for path in interpreters if safe(path, True) and path.is_file()), sys.executable)
        code, reason = execute([python, "-I", "-c", "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('pytest') else 1)"], directory, 3)
        if code != 0:
            return [], [], "pytest недоступен локально" + (" (timeout)" if reason == "timeout" else "")
        args = [python, "-B", "-m", "pytest", "-c", str(config), "-o", "addopts=",
                "-p", "no:cacheprovider", "-q", str(tests)]
        return args, [config, Path(python)], ""
    if not any(re.search(r"\.(?:test|spec)\.[cm]?[jt]sx?$", path.name) for path in files):
        return [], [], "нет существующих тестов frontend"
    config = vitest_config(directory)
    if config is None:
        return [], [], "нет конфигурации Vitest"
    package = directory / "package.json"
    if not safe(package) or not package.is_file():
        return [], [], "нет package.json frontend"
    manifest = json.loads(package.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("package.json must be an object")
    if "vitest" not in {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}:
        return [], [], "Vitest не объявлен в зависимостях"
    tool = next((parent / "node_modules/vitest/vitest.mjs" for parent in (directory, ROOT)
                 if safe(parent / "node_modules/vitest/vitest.mjs", True) and
                 (parent / "node_modules/vitest/vitest.mjs").is_file()), None)
    node = shutil.which("node")
    if not node or tool is None:
        return [], [], "нет локального Vitest или Node.js"
    return [node, str(tool), "run", "--config", str(config), "--watch=false",
            "--update=false", "--passWithNoTests=false", "--no-cache"], [config, package, tool, Path(node)], ""


def run_suite(suite: str, state: dict) -> str:
    files = inventory(ROOT / suite)
    args, inputs, reason = plan(suite, files)
    if not args:
        return f"{suite}: SKIPPED — {reason}."
    digest = hashlib.sha256(json.dumps(args).encode())
    # Include tests, public source, configuration, lockfiles and tool identity.
    for path in sorted(set(files + inputs + [ROOT / name for name in (
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock")
            if safe(ROOT / name) and (ROOT / name).is_file()])):
        digest.update(str(path).encode())
        digest.update(path.read_bytes())
    fingerprint = digest.hexdigest()
    previous = state.get(suite, {})
    if not isinstance(previous, dict):
        previous = {}
    if previous.get("fingerprint") == fingerprint:
        return f"{suite}: SKIPPED — код и тесты не изменились; предыдущий результат {previous.get('status')}."
    code, reason = execute(args, ROOT / suite, TIMEOUT)
    if reason == "unavailable":
        return f"{suite}: SKIPPED — инструмент не удалось запустить."
    if reason == "no-tests" or (suite == "backend" and code == 5):
        status, detail = "SKIPPED", "тесты не найдены выбранной конфигурацией"
    elif reason == "timeout":
        status, detail = "FAILED", f"timeout: превышено {TIMEOUT} секунд"
    elif code == 0:
        status, detail = "PASSED", "набор тестов завершился с кодом 0"
    else:
        status, detail = "FAILED", f"тестовый процесс завершился с кодом {code}"
    state[suite] = {"fingerprint": fingerprint, "status": status}
    return f"{suite}: {status} — {detail}."


def main() -> None:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("event")
        if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") not in {"apply_patch", "Edit", "Write"}:
            return
        suites = affected(event)
        if not suites:
            emit(["SKIPPED — нет изменений исходников backend/frontend (документация, Harness и OpenSpec исключены)."])
            return
        # One lock for this repository/session prevents duplicate concurrent runs.
        key = hashlib.sha256((str(ROOT) + str(event.get("session_id", "default"))).encode()).hexdigest()
        cache = Path(tempfile.gettempdir()) / "codex-test-runner-v1"
        cache.mkdir(exist_ok=True)
        lock = cache / (key + ".lock")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # A killed hook can leave a stale lock. Remove only our expired lock;
            # defer this event so two invocations never both acquire it here.
            if time.time() - lock.stat().st_mtime > 120:
                lock.unlink(missing_ok=True)
            emit(["SKIPPED — набор уже выполняется или снимается устаревшая блокировка."])
            return
        os.close(descriptor)
        try:
            state_path = cache / (key + ".json")
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    state = {}
            except (OSError, ValueError):
                state = {}
            messages = [run_suite(suite, state) for suite in sorted(suites)]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            emit(messages)
        finally:
            lock.unlink(missing_ok=True)
    except (ValueError, OSError, RuntimeError, TypeError, configparser.Error) as error:
        emit([f"SKIPPED — событие/конфигурация недоступны или некорректны ({type(error).__name__})."])


if __name__ == "__main__":
    main()
