@AGENTS.md

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `.venv/Scripts/python.exe -m graphify query "<question>"` when graphify-out/graph.json exists. Use `... -m graphify path "<A>" "<B>"` for relationships and `... -m graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Never call the bare `graphify` command: group policy blocks `.venv/Scripts/graphify.exe` on this laptop ("not recognized" / "blocked by group policy"). Always go through `.venv/Scripts/python.exe -m graphify`.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `.venv/Scripts/python.exe -m graphify update .` to keep the graph current (AST-only, no API cost).
