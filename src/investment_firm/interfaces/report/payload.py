"""Build the JSON result dict for a finished committee run.

Shared by the web UI (``web/runs.py``) and the CLI ``--report`` flag, and the
single input of :func:`render_committee_report`. No fastapi import.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import investment_firm
from investment_firm.core.glossary import find_terms
from investment_firm.core.horizon import HORIZONS, resolve_horizon
from investment_firm.core.schemas import Memo
from investment_firm.llm.costs import RunTracker

_FALLBACK_RISK = "model did not return structured JSON"

STANCE_PLAIN = {
    "BULLISH": "Positive (expects prices to rise)",
    "BEARISH": "Negative (expects prices to fall)",
    "NEUTRAL": "Neutral (no strong view)",
    "ERROR": "Failed (no view produced)",
}

RECOMMENDATION_PLAIN = {
    "BUY": "Favourable — the committee sees more upside than downside",
    "SELL": "Unfavourable — the committee sees more downside than upside",
    "HOLD": "Neutral — no strong reason to change exposure",
    "AVOID": "Unattractive — risks outweigh the potential reward",
    "ERROR": "No ruling — the final step failed",
}


def _warnings(memo: Memo, tracker: RunTracker) -> List[str]:
    warnings: List[str] = []
    for view in memo.views:
        if view.stance == "ERROR":
            warnings.append(
                f"{view.role}: ERROR — {view.error or 'analysis step failed'}"
            )
        if _FALLBACK_RISK in view.key_risks or _FALLBACK_RISK in view.rationale:
            warnings.append(
                f"{view.role}: model did not return structured JSON — "
                "rationale contains raw text fallback."
            )
        for risk in view.key_risks:
            if risk.startswith("API error"):
                warnings.append(f"{view.role}: API error — {risk}")
        if not view.grounded:
            warnings.append(
                f"{view.role}: ungrounded — no successful tool call or web "
                "citation backed this view."
            )
    if tracker.token_budget > 0 and tracker.total_tokens >= tracker.token_budget:
        warnings.append(
            f"Token budget reached or exceeded: "
            f"{tracker.total_tokens} / {tracker.token_budget} tokens used."
        )
    for model_name in tracker.unpriced_models():
        warnings.append(
            f"Cost estimate for {model_name} uses family/default fallback pricing "
            "— add the model to config/costs.yaml for an accurate figure."
        )
    for model_name in tracker.vendor_priced_models():
        warnings.append(
            f"{model_name} ran on Databricks but has no databricks: entry in "
            "config/costs.yaml — costed at vendor list rates, which Databricks "
            "does not bill."
        )
    for model_name in tracker.estimated_models():
        warnings.append(
            f"Databricks has no published rate for {model_name} — its cost is "
            "estimated from the nearest published sibling."
        )
    return warnings


def _glossary(memo: Memo) -> List[Dict[str, str]]:
    found = find_terms(
        memo.summary,
        memo.headline,
        *memo.key_reasons,
        *memo.main_risks,
        *memo.what_to_watch,
        memo.briefing,
        memo.debate_summary,
        *(v.rationale for v in memo.views),
        *(r for v in memo.views for r in v.key_risks),
        *(t.text for t in memo.debate),
    )
    return [
        {"term": e.term, "plain": e.plain, "how_calculated": e.how_calculated}
        for e in found
    ]


def build_run_result(
    memo: Memo, tracker: RunTracker, *, horizon: str = "short", run_id: str = ""
) -> Dict[str, Any]:
    """Return the JSON-safe result envelope that feeds every UI tab and the report."""
    hz = resolve_horizon(memo.horizon or horizon)
    call_records = [
        {
            "agent": r.agent,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_tokens": r.total_tokens,
            "cost_units": round(r.cost_units, 4),
            "cost_usd_input": round(r.cost_usd_input, 6),
            "cost_usd_output": round(r.cost_usd_output, 6),
            "cost_usd": round(r.cost_usd, 6),
            "price_source": r.price_source,
            "price_basis": r.price_basis,
            "price_confidence": r.price_confidence,
            "backend": r.backend,
            "latency_s": round(r.latency_s, 3),
        }
        for r in tracker.records
    ]

    return {
        "recommendation": memo.recommendation,
        "summary": memo.summary,
        "profile": memo.profile,
        "question": memo.question,
        "briefing": memo.briefing,
        "briefing_role": memo.briefing_role,
        "briefing_model": memo.briefing_model,
        "views": [
            {
                "role": v.role,
                "model": v.model,
                "stance": v.stance,
                "conviction": v.conviction,
                "rationale": v.rationale,
                "error": v.error,
                "key_risks": v.key_risks,
                "evidence": v.evidence,
                "grounded": v.grounded,
                "citations": [c.model_dump() for c in v.citations],
            }
            for v in memo.views
        ],
        "sources": memo.all_sources(),
        "web_sources": [s.model_dump() for s in memo.web_sources],
        "debate": [t.model_dump() for t in memo.debate],
        "debate_summary": memo.debate_summary,
        "synth_role": memo.synth_role,
        "synth_model": memo.synth_model,
        "debate_judge_role": memo.debate_judge_role,
        "debate_judge_model": memo.debate_judge_model,
        "cost_summary": tracker.render_summary(),
        "cost_usd_estimate": round(tracker.total_usd, 4),
        "cost_usd_input_estimate": round(tracker.total_usd_input, 4),
        "cost_usd_output_estimate": round(tracker.total_usd_output, 4),
        "cost_units_total": round(tracker.total_cost, 4),
        "total_tokens": tracker.total_tokens,
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "token_budget": tracker.token_budget,
        "cost_by_model": tracker.by_model(),
        "cost_unpriced_models": tracker.unpriced_models(),
        "cost_estimated_models": tracker.estimated_models(),
        "cost_vendor_priced_models": tracker.vendor_priced_models(),
        "call_records": call_records,
        "warnings": _warnings(memo, tracker),
        "disclaimer": investment_firm.DISCLAIMER,
        "horizon": hz.key,
        "horizon_label": HORIZONS[hz.key].label,
        "headline": memo.headline,
        "key_reasons": list(memo.key_reasons),
        "main_risks": list(memo.main_risks),
        "what_to_watch": list(memo.what_to_watch),
        "confidence": memo.confidence,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": run_id,
        "report_url": f"/api/runs/{run_id}/report.html" if run_id else "",
        "glossary": _glossary(memo),
        "stance_plain": dict(STANCE_PLAIN),
        "recommendation_plain": RECOMMENDATION_PLAIN.get(memo.recommendation, ""),
    }
