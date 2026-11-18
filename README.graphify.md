# graphify in this repo

graphify turns the repo into a knowledge graph (`graphify-out/`) that AI assistants can query
instead of grepping raw files. This note covers day-to-day use on the DBAG laptop.

> AppLocker blocks the `graphify.exe` launcher. Always run it as a module:
> `.venv\Scripts\python.exe -m graphify ...`

## Files

| Path | What it is |
| --- | --- |
| `graphify-out/graph.json` | The graph. Its existence switches the hooks and instructions on. |
| `graphify-out/GRAPH_REPORT.md` | Human-readable summary (god nodes, communities, suggested questions). |
| `graphify-out/graph.html` | Interactive viewer. Open in a browser. |
| `graphify-out/manifest.json`, `cache/` | Change tracking and extraction cache used by `update`. |
| `graphify-out/cost.json` | Token spend of past full runs. |

## Keep it current

The graph is a snapshot. After renaming, moving or adding files, refresh it:

```powershell
.venv\Scripts\python.exe -m graphify update .
```

- Code only (AST), no LLM, no token cost.
- Docs, markdown and images need the full pipeline: type `/graphify` in Copilot Chat
  (or Claude Code). Use `/graphify . --update` to re-extract only changed files.
- A stale graph makes agents answer confidently from old structure. When in doubt, run `update`.
- Optional auto-rebuild: `/graphify . --watch`, or the post-commit hook described in
  `.claude/skills/graphify/references/hooks.md`.

## Query it yourself

```powershell
.venv\Scripts\python.exe -m graphify query "how does the committee pick analysts?"
.venv\Scripts\python.exe -m graphify path "Orchestrator" "Agent"
.venv\Scripts\python.exe -m graphify explain "RunTracker"
```

Extras for `query`: `--dfs` (trace one path), `--budget 1500` (cap answer tokens).

## How the assistants are pointed at it

| Mechanism | Where | Strength |
| --- | --- | --- |
| Instructions | `.github/copilot-instructions.md`, `CLAUDE.md` | Advisory text, read every session. |
| Skill | `.claude/skills/graphify/SKILL.md` (`/graphify`) | Loaded by name or description match. |
| Hook | `.claude/settings.json` (PreToolUse) | Adds a "use graphify first" nudge when a shell command contains `grep`, `rg`, `find`, etc., or when reading source/doc files. Never blocks. |

Nothing forces the agent to obey; they are nudges.

### Hook details

The hooks run `"<abs>/.venv/Scripts/python.exe" "<abs>/.claude/graphify_guard.py" search|read`.
`graphify_guard.py` is a fail-open wrapper around `graphify hook-guard`. Paths must be quoted, absolute,
and forward-slash so they work in cmd.exe (Copilot CLI) and Git Bash (Claude Code). The hooks read the tool
call as JSON on stdin, so running them bare just waits for input (Ctrl+C). To test, pipe input in:

```powershell
'{"tool_input":{"command":"grep foo"}}' | .venv\Scripts\python.exe .claude\graphify_guard.py search
```

Expected: one JSON line with `"MANDATORY: graphify-out/graph.json exists..."`. Input like `'{}'`
prints nothing. Both exit 0.

Do not re-run `graphify claude install` (or similar installers): they rewrite the hooks to the
blocked `graphify.exe` path. If you see `Denied by preToolUse hook ... (hook errored)`, the hook
command has been reset to the `.exe`; change it back to the `python.exe -m graphify` form.

## Check that GitHub Copilot is using it

No single switch proves it. Combine these:

1. **Instructions loaded**: in a Copilot Chat answer, expand "Used N references". `copilot-instructions.md`
   should be listed.
2. **Skill visible**: typing `/` in Copilot Chat should list `graphify`.
3. **Behaviour**: ask an architecture question ("where is the planner and what calls it?"). A good
   run shows a `graphify query ...` tool or terminal call before any file reads or grep.
4. **Hook firing**: run a grep-style command through the agent. No hook error means it ran. For
   detail, search the Copilot debug logs (VS Code: the `GitHub.copilot-chat\debug-logs` folder under
   your workspaceStorage) for `graphify`.
5. **Graph present and fresh**: `graphify-out/graph.json` must exist, and its modified time should be
   newer than your last code change. If it is not, run `update`.

Verified in this repo: VS Code Copilot Chat lists the `graphify` skill from `.claude/skills/`. Not
verified: whether Copilot CLI reads `.claude/skills/` (it documents `.github/skills/` and
`~/.copilot/skills/`).

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Hook errored, commands denied | Hook points at `graphify.exe` (AppLocker). Use `python.exe -m graphify`. |
| Hook command hangs in terminal | It is waiting for stdin. Pipe JSON in, or Ctrl+C. |
| Agent ignores graphify | Nudges are advisory; ask explicitly ("use graphify query first"). |
| Answers mention files that no longer exist | Stale graph. Run `update`. |
| `GRAPH_REPORT.md` missing docs content | `update` is AST-only. Run `/graphify` for docs. |
