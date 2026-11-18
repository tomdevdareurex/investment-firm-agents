"""Fail-open wrapper around ``python -m graphify hook-guard <mode>``.

Claude Code treats a crashing PreToolUse hook as a *deny*, which on this laptop
blocked Read/Glob/Bash whenever graphify was missing or errored. This wrapper
forwards stdin to graphify and preserves an intentional deny (exit code 2 or a
JSON ``permissionDecision``), but any crash/import error/missing module exits 0
so the tool call is allowed.
"""

from __future__ import annotations

import runpy
import sys


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "read"
    sys.argv = ["graphify", "hook-guard", mode]
    try:
        runpy.run_module("graphify", run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        code = exc.code
        return 2 if code == 2 else 0
    except BaseException:  # noqa: BLE001 - fail open on purpose
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
