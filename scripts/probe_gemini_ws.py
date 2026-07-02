"""One-off probe: find the payload shape that actually grounds Gemini web search.

    .venv\\Scripts\\python.exe scripts\\probe_gemini_ws.py
"""
from __future__ import annotations

import datetime

from investment_firm.llm import client
from investment_firm.llm.utils import extract_text, is_error, get_error_message

TODAY = datetime.date.today().isoformat()
Q = (f"Today is {TODAY}. What is the ECB deposit facility rate today? "
     "One sentence, cite source and the as-of date of your information.")
MSGS = [{"role": "user", "content": Q}]

VARIANTS = [
    ("webSearch camelCase flag", {"webSearch": True}),
    ("web_search_options (OpenAI)", {"web_search_options": {}}),
    ("tools googleSearch (Gemini native)", {"tools": [{"googleSearch": {}}]}),
    ("tools google_search snake", {"tools": [{"google_search": {}}]}),
    ("tools type=web_search", {"tools": [{"type": "web_search"}]}),
]


def main() -> None:
    for label, extra in VARIANTS:
        try:
            resp = client.chat("gemini-2.5-flash", MSGS, max_tokens=800, extra=extra)
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] EXCEPTION: {exc}")
            continue
        if is_error(resp):
            print(f"[{label}] ERROR: {str(get_error_message(resp))[:200]}")
        else:
            print(f"[{label}] ok: {extract_text(resp, strict=False)[:300]}")
        print()


if __name__ == "__main__":
    main()
