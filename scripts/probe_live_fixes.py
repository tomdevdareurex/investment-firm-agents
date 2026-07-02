"""One-off live probe: verify Claude tool_choice conversion + Gemini web-search grounding.

Spends a small number of tokens. Run manually:
    .venv\\Scripts\\python.exe scripts\\probe_live_fixes.py
"""
from __future__ import annotations

import datetime
import json

from investment_firm.llm import client
from investment_firm.llm.utils import extract_text, extract_tool_calls, is_error, get_error_message

TODAY = datetime.date.today().isoformat()

TOOL = [{
    "type": "function",
    "function": {
        "name": "get_ecb_rate",
        "description": "Return the current ECB main refinancing rate.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}]


def show(label: str, resp: dict) -> None:
    if is_error(resp):
        print(f"[{label}] ERROR: {get_error_message(resp)}")
        return
    calls = extract_tool_calls(resp)
    text = extract_text(resp, strict=False)
    print(f"[{label}] ok. tool_calls={[c['function']['name'] for c in calls] if calls else None}")
    print(f"  text: {text[:400]}")


def main() -> None:
    # Probe 1: Claude + OpenAI-format tools + tool_choice="auto" (the exact failing shape)
    resp = client.chat(
        "claude-4.5-haiku",
        [{"role": "system", "content": "You are a rates analyst."},
         {"role": "user", "content": "What is the ECB policy rate? Use the tool."}],
        max_tokens=300,
        tools=TOOL,
        tool_choice="auto",
    )
    show("claude tools", resp)

    # Probe 2: Claude native web search (known-good path) — freshness check
    resp = client.chat(
        "claude-4.5-haiku",
        [{"role": "user", "content": f"Today is {TODAY}. What is the ECB deposit facility rate today? One sentence, cite source and date."}],
        max_tokens=500,
        web_search=True,
        max_uses=1,
    )
    show("claude websearch", resp)

    # Probe 3: Gemini generic web_search flag — freshness check
    resp = client.chat(
        "gemini-2.5-flash",
        [{"role": "user", "content": f"Today is {TODAY}. What is the ECB deposit facility rate today? One sentence, cite source and the as-of date of your information."}],
        max_tokens=300,
        web_search=True,
        max_uses=1,
    )
    show("gemini flag=web_search", resp)

    # Probe 4: Gemini control — NO web search (to compare staleness)
    resp = client.chat(
        "gemini-2.5-flash",
        [{"role": "user", "content": f"Today is {TODAY}. What is the ECB deposit facility rate today? One sentence, state the as-of date of your information."}],
        max_tokens=300,
    )
    show("gemini control (no ws)", resp)


if __name__ == "__main__":
    main()
