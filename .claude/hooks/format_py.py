"""PostToolUse: format edited ``.py`` files with black (best effort, never fails).

Invoked as ``.venv/Scripts/python.exe .claude/hooks/format_py.py`` from the repo root (see
``block_env.py`` for why the command is quote-free).  Accepts Claude Code and Copilot payloads.
"""

import json
import subprocess
import sys

from block_env import candidate_paths


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw or "{}")
        files = [p for p in candidate_paths(payload) if p.endswith(".py")]
        if files:
            subprocess.run(
                [sys.executable, "-m", "black", "-q", "-t", "py312", *files],
                capture_output=True,
                timeout=60,
            )
    except Exception:  # noqa: BLE001 - formatting is optional
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())