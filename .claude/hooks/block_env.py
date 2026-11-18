"""PreToolUse guard: deny edits/writes to .env files (``.env.example`` allowed).

Invoked as ``.venv/Scripts/python.exe .claude/hooks/block_env.py`` from the repo root -- a
quote-free command that runs unchanged in bash (Claude Code) and PowerShell (VS Code /
Copilot, which copies ``command`` to its ``powershell`` field on Windows).  Reads Claude
Code (``tool_input.file_path``) and Copilot (``tool_input``/``toolArgs`` with ``path`` or
``filePath``) payloads.  It never raises: a crashing PreToolUse hook makes the harness
deny every edit.  Blocking uses exit code 2 + stderr, honoured by both harnesses.
"""

import json
import os
import re
import sys

PATH_KEYS = ("file_path", "path", "filePath", "notebook_path", "paths")
REASON = "Blocked: .env files contain API credentials"
_RAW_ENV = re.compile(r"""(?:^|[\\/"'\s])(\.env(?:\.[\w-]+)*)(?=[\\"'\s,}\]]|$)""")


def is_blocked(path) -> bool:
    b = os.path.basename(str(path).rstrip("\\/"))
    return b == ".env" or (b.startswith(".env.") and b != ".env.example")


def candidate_paths(payload: dict):
    for key in ("tool_input", "toolArgs", "input", "arguments"):
        args = payload.get(key)
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        if not isinstance(args, dict):
            continue
        for k in PATH_KEYS:
            v = args.get(k)
            if isinstance(v, str):
                yield v
            elif isinstance(v, list):
                yield from (x for x in v if isinstance(x, str))


def decide(raw: str) -> bool:
    """True when the tool call must be denied."""
    try:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        return any(is_blocked(p) for p in candidate_paths(payload))
    except ValueError:
        return any(is_blocked(m) for m in _RAW_ENV.findall(raw or ""))


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if not decide(raw):
            return 0
    except Exception:  # noqa: BLE001 - fail open on hook bugs, never block every edit
        return 0
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }
    print(json.dumps(out))
    print(REASON, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())