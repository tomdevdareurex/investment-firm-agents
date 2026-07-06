"""Pydantic schemas for analyst views and the Investment Committee memo (M1).

These are deliberately small at M1 (single-asset memo from a few analysts). Later
milestones extend them with provenance/SOURCES (M1.5) and the full committee vote (M2).
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

Stance = Literal["BULLISH", "BEARISH", "NEUTRAL"]
Recommendation = Literal["BUY", "SELL", "HOLD", "AVOID"]

_STRUCTURAL_ONLY = set(" \t\n[]{}:,\"'")


def _clean_display_list(items: List[str]) -> List[str]:
    """Drop empty or punctuation-only fragments (leaked JSON structure) for display."""
    out: List[str] = []
    for item in items:
        text = str(item).strip()
        if text and not set(text) <= _STRUCTURAL_ONLY:
            out.append(text)
    return out


class Source(BaseModel):
    """A verifiable source reference (real URL captured from web search or tools)."""

    url: str
    title: str = ""
    origin: str = "web"  # web:claude | web:gemini | tool | briefing
    verified: bool = True

    def label(self) -> str:
        return f"{self.title} — {self.url}" if self.title else self.url


class DebateTurn(BaseModel):
    """One turn in the bull/bear investment debate."""

    speaker: str  # "Bull" | "Bear" | "Judge"
    text: str = ""

    def render(self) -> str:
        return f"{self.speaker}: {self.text.strip()}"


class AnalystView(BaseModel):
    """One analyst's structured opinion on the question."""

    role: str
    model: str = ""
    stance: Stance = "NEUTRAL"
    conviction: int = Field(default=3, ge=1, le=5, description="1 (low) .. 5 (high)")
    rationale: str = ""
    key_risks: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(
        default_factory=list, description="provenance-tagged datapoints used"
    )
    grounded: bool = Field(
        default=False,
        description="True if at least one successful tool call or web citation backed this view",
    )
    citations: List[Source] = Field(
        default_factory=list,
        description="real web-search source URLs captured this run",
    )

    def render(self) -> str:
        clean_risks = _clean_display_list(self.key_risks)
        risks = "; ".join(clean_risks) if clean_risks else "none stated"
        lines = [
            f"[{self.role}] ({self.model})",
            f"  stance: {self.stance} | conviction: {self.conviction}/5",
            f"  rationale: {self.rationale.strip()}",
            f"  key risks: {risks}",
        ]
        if self.evidence:
            lines.append("  evidence: " + "; ".join(self.evidence))
        return "\n".join(lines)


class Memo(BaseModel):
    """A single-asset Investment Committee memo (M1)."""

    question: str
    profile: str = ""
    recommendation: Recommendation = "HOLD"
    summary: str = ""
    views: List[AnalystView] = Field(default_factory=list)
    briefing: str = ""
    debate: List[DebateTurn] = Field(
        default_factory=list, description="bull/bear debate transcript (if run)"
    )
    debate_summary: str = Field(
        default="", description="judge's verdict distilling the debate"
    )
    sources: List[str] = Field(default_factory=list)
    web_sources: List[Source] = Field(
        default_factory=list, description="real web-search URLs captured across the run"
    )
    disclaimer: str = ""

    def all_sources(self) -> List[str]:
        """Return deduplicated sources from the packet plus every analyst's evidence."""
        seen: List[str] = list(self.sources)
        for view in self.views:
            for item in view.evidence:
                if item not in seen:
                    seen.append(item)
        for src in self.web_sources:
            label = src.label()
            if label not in seen:
                seen.append(label)
        out: List[str] = []
        for item in seen:
            if item not in out:
                out.append(item)
        return out

    def render(self) -> str:
        lines: List[str] = []
        lines.append("=" * 72)
        lines.append("INVESTMENT COMMITTEE MEMO (M1.5 — agentic, data-backed)")
        lines.append("=" * 72)
        lines.append(f"Question: {self.question}")
        if self.profile:
            lines.append(f"Profile:  {self.profile}")
        lines.append("")
        lines.append(f"RECOMMENDATION: {self.recommendation}")
        lines.append("")
        lines.append("Summary:")
        lines.append(f"  {self.summary.strip()}")
        lines.append("")
        lines.append("-" * 72)
        lines.append("Analyst views:")
        lines.append("-" * 72)
        for view in self.views:
            lines.append(view.render())
            lines.append("")
        if self.debate:
            lines.append("-" * 72)
            lines.append("BULL / BEAR DEBATE:")
            lines.append("-" * 72)
            for turn in self.debate:
                lines.append(turn.render())
                lines.append("")
            if self.debate_summary:
                lines.append("Debate verdict:")
                lines.append(f"  {self.debate_summary.strip()}")
                lines.append("")
        sources = self.all_sources()
        if sources:
            lines.append("-" * 72)
            lines.append("SOURCES:")
            for src in sources:
                lines.append(f"  - {src}")
            lines.append("")
        if self.disclaimer:
            lines.append("-" * 72)
            lines.append(self.disclaimer)
        return "\n".join(lines)
