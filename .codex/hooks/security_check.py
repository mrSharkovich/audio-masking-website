"""First-stage terminal policy; reads stdin only, never executes or logs commands.

This is a lexical guardrail, not a shell parser or a security boundary. Dynamic
commands, aliases, scripts, encoded payloads and later interactive input may bypass
it. Literal executable names inside arguments may produce conservative denials.
"""

import json
import re
import sys


BLOCKED_GIT_COMMANDS = frozenset({"push", "pull", "fetch", "clone", "ls-remote"})
TERMINAL_TOOLS = frozenset({"Bash", "exec_command", "shell", "shell_command"})
TOKEN_PATTERN = re.compile(r'''"[^"\n]*"|'[^'\n]*'|[^\s;|&(){}]+|[;|&(){}\n]''')
SEPARATORS = frozenset(";|&(){}\n")
GIT_VALUE_OPTIONS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--config-env"})


def executable_name(token: str) -> str:
    """Recognize literal Windows/Unix paths, quotes and executable suffixes."""
    name = token.strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def blocked_reason(command: str, depth: int = 0) -> str | None:
    tokens = TOKEN_PATTERN.findall(command)
    for index, token in enumerate(tokens):
        name = executable_name(token)
        if name == "gh":
            return "Security Check: GitHub CLI (gh) запрещён правилами проекта."
        if name == "git":
            cursor = index + 1
            while cursor < len(tokens):
                argument = tokens[cursor].strip("\"'")
                if argument in SEPARATORS:
                    break
                if argument in GIT_VALUE_OPTIONS:
                    cursor += 2
                    continue
                if argument.startswith("-"):
                    cursor += 1
                    continue
                if argument.lower() in BLOCKED_GIT_COMMANDS:
                    return "Security Check: сетевые Git-команды push, pull, fetch, clone и ls-remote запрещены."
                break
        # Inspect literal nested shell command strings without evaluating them.
        if depth < 3 and token[:1] in {"'", '"'} and any(char.isspace() for char in token):
            reason = blocked_reason(token[1:-1], depth + 1)
            if reason:
                return reason
    return None


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=True))


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        deny("Security Check: некорректное JSON-событие; команда не проверена.")
        return
    if not isinstance(event, dict):
        deny("Security Check: ожидается JSON-объект события.")
        return
    if event.get("hook_event_name") != "PreToolUse":
        return
    if event.get("tool_name") not in TERMINAL_TOOLS:
        return
    tool_input = event.get("tool_input")
    command = None
    if isinstance(tool_input, dict):
        command = tool_input.get("command", tool_input.get("cmd"))
    if not isinstance(command, str):
        deny("Security Check: отсутствует поддерживаемая строка команды; команда не проверена.")
        return
    reason = blocked_reason(command)
    if reason:
        deny(reason)
    # Successful check: exit 0 without output, preserving normal Codex approvals.


if __name__ == "__main__":
    main()
