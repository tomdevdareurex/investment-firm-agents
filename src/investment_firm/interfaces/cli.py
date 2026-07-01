"""Command-line interface.

Exposes connectivity/budget checks (``--models``/``--tokens``), a cheap end-to-end smoke
test (``--smoke``), a web-search probe (``--probe-websearch``), and the agentic
Investment Committee run (``investment-firm "<question>"``): a briefing built with data
tools, a planner that picks analysts, tool-using analyst agents, and a synthesized memo.
Use ``--simple`` for a cheaper fixed run. The full parallel committee with voting is M2.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Optional, Sequence

from .. import DISCLAIMER, __version__
from ..llm import client, config
from ..llm.costs import RunTracker
from ..llm.models import DEFAULT_CHAT_MODEL
from ..llm.utils import PlaygroundError, extract_text, extract_usage

_SMOKE_MODEL = DEFAULT_CHAT_MODEL  # cheap
_PROBE_PROMPT = "What was the most recent ECB monetary policy decision, and on what date?"


def _print_disclaimer() -> None:
    print(f"[investment-firm-agents] {DISCLAIMER}\n")


def cmd_models() -> int:
    """List available models (no chat tokens spent)."""
    models = client.list_models()
    names = _model_names(models)
    print(f"{len(names)} models available:")
    for name in names:
        print(f"  - {name}")
    return 0


def _model_names(models: object) -> list:
    """Best-effort extraction of model names from the /ai/models payload."""
    if isinstance(models, list):
        out = []
        for item in models:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                out.append(item.get("id") or item.get("name") or json.dumps(item))
        return out
    if isinstance(models, dict) and isinstance(models.get("data"), list):
        return _model_names(models["data"])
    return [str(models)]


def cmd_tokens() -> int:
    """Show monthly token usage (no chat tokens spent)."""
    usage = client.get_token_usage()
    used = usage.get("used", "?")
    total = usage.get("total", "?")
    print(f"token usage: used={used} total={total}")
    return 0


def cmd_smoke() -> int:
    """Connectivity + budget + one cheap chat call, end to end."""
    _print_disclaimer()
    print("1/3 listing models ...")
    names = _model_names(client.list_models())
    print(f"    ok — {len(names)} models (e.g. {', '.join(names[:4])})")

    print("2/3 checking token budget ...")
    usage = client.get_token_usage()
    print(f"    ok — used={usage.get('used', '?')} total={usage.get('total', '?')}")

    print(f"3/3 asking {_SMOKE_MODEL} a one-line question ...")
    tracker = RunTracker()
    start = time.perf_counter()
    resp = client.chat(
        _SMOKE_MODEL,
        [{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=20,
    )
    elapsed = time.perf_counter() - start
    text = extract_text(resp, strict=False).strip()
    inp, out, _ = extract_usage(resp)
    tracker.record(_SMOKE_MODEL, _SMOKE_MODEL, inp, out, elapsed)
    print(f"    ok — reply: {text!r} ({elapsed:.1f}s)")
    print()
    print(tracker.render_summary())
    print("\nSmoke test passed.")
    return 0


def cmd_probe_websearch(model: str) -> int:
    """Send one search-requiring prompt with web search ON and print the raw shape.

    Before spending a call, this checks the model's advertised ``webSearch`` capability
    via ``/ai/models``: GPT/Kimi/o-series models report ``webSearch: false`` and would
    only return an "Unknown parameter" error, so the probe is skipped with a clear note.
    This complements the browser F12 capture documented in the README. Record your
    conclusion in the README findings table.
    """
    _print_disclaimer()

    supported = client.supports_websearch(model)
    if supported is False:
        print(
            f"{model!r} reports webSearch=false in /ai/models — web search is not "
            f"supported here, so the probe is skipped (no tokens spent).\n"
            "On this Playground only Claude and Gemini chat models support web search; "
            "GPT, Kimi and o-series models do not. Try e.g. gemini-2.5-flash or a "
            "Claude model."
        )
        return 2
    if supported is None:
        print(
            f"[warn] could not confirm {model!r}'s webSearch capability from "
            "/ai/models (model not listed) — probing anyway.\n"
        )

    print(f"Probing web search on {model!r} (mode=generic, flag={config.websearch_flag()!r}) ...\n")

    try:
        resp = client.chat(
            model,
            [{"role": "user", "content": _PROBE_PROMPT}],
            web_search=True,
            web_search_mode="generic",
            max_uses=2,
        )
    except PlaygroundError as exc:
        print(f"[error] {exc}")
        return 1

    keys = sorted(resp.keys()) if isinstance(resp, dict) else []
    print(f"response top-level keys: {keys}")
    text = extract_text(resp, strict=False)
    snippet = text.strip().replace("\n", " ")[:300]
    print(f"text snippet: {snippet!r}")
    inp, out, total = extract_usage(resp)
    print(f"usage: input={inp} output={out} total={total}")
    print(
        "\nInterpretation: if this returned current, grounded text without an error, the "
        "generic flag likely works for this model (hypothesis A). Cross-check with the "
        "F12 → Network payload to confirm the exact request key, then record it in the "
        "README findings table."
    )
    return 0


def cmd_run(question: str, profile: Optional[str] = None, simple: bool = False) -> int:
    """Run the Investment Committee for a question and print the memo.

    Default is the full agentic flow (briefing → plan → tool-using analysts →
    synthesis). ``simple`` runs the cheaper M1-style fixed sequence with no tools/planner.
    """
    from ..core.orchestrator import run_committee
    from ..core.roster import RosterError

    _print_disclaimer()
    if config.call_pause() == 0 and not simple:
        print(
            "[tip] multi-agent runs make many calls quickly. If you hit a tokens-per-"
            "minute limit, set IFA_CALL_PAUSE=2 (seconds between calls) or use --simple.\n"
        )
    try:
        memo, tracker = run_committee(question, profile=profile, simple=simple)
    except RosterError as exc:
        print(f"[roster] {exc}", file=sys.stderr)
        return 2
    print(memo.render())
    print()
    print(tracker.render_summary())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investment-firm",
        description=(
            "Investment-firm-agents: run a multi-agent committee on a question, plus "
            "connectivity/smoke/web-search utilities."
        ),
    )
    parser.add_argument("question", nargs="?", help="the decision question to run")
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="firm profile to use (budget|balanced|premium); overrides IFA_PROFILE",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="cheaper fixed 3-analyst run with no tools/planner (fewer calls)",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--models", action="store_true", help="list models (no tokens)")
    parser.add_argument("--tokens", action="store_true", help="show token usage (no tokens)")
    parser.add_argument("--smoke", action="store_true", help="run the end-to-end smoke test")
    parser.add_argument(
        "--probe-websearch",
        metavar="MODEL",
        help="send one web-search prompt to MODEL and print the raw response shape",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)

    if args.version:
        print(f"investment-firm-agents {__version__}")
        return 0

    try:
        if args.models:
            return cmd_models()
        if args.tokens:
            return cmd_tokens()
        if args.smoke:
            return cmd_smoke()
        if args.probe_websearch:
            return cmd_probe_websearch(args.probe_websearch)
        if args.question:
            return cmd_run(args.question, profile=args.profile, simple=args.simple)
    except config.ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2
    except PlaygroundError as exc:
        print(f"[api] {exc}", file=sys.stderr)
        return 1

    build_parser().print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
