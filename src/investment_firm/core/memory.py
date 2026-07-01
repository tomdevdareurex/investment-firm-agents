"""Lightweight memory/state for agents and a run (M1.5).

Two scopes:

* :class:`ScratchMemory` — an agent's working notes accumulated *within* one task
  (observations from tool calls, intermediate reasoning the agent chooses to keep).
* :class:`RunMemory` — shared state threaded *between* agents across a single run: the
  briefing packet plus each agent's recorded findings, so later agents can build on
  earlier ones (the M1.5 "shared context" the orchestrator passes around).

Embeddings-based long-term recall across runs stays in M3; this is deliberately simple
and in-process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ScratchMemory:
    """An agent's per-task working memory."""

    notes: List[str] = field(default_factory=list)

    def remember(self, note: str) -> None:
        text = note.strip()
        if text:
            self.notes.append(text)

    def render(self) -> str:
        if not self.notes:
            return ""
        return "Working notes:\n" + "\n".join(f"- {n}" for n in self.notes)


@dataclass
class RunMemory:
    """Shared state threaded between agents during one run."""

    briefing: str = ""
    findings: Dict[str, str] = field(default_factory=dict)

    def set_briefing(self, text: str) -> None:
        self.briefing = (text or "").strip()

    def record_finding(self, role: str, summary: str) -> None:
        summary = (summary or "").strip()
        if summary:
            self.findings[role] = summary

    def context_for(self, role: Optional[str] = None) -> str:
        """Render the shared context an agent should see before acting."""
        parts: List[str] = []
        if self.briefing:
            parts.append("BRIEFING PACKET (provenance-tagged):\n" + self.briefing)
        peers = {r: s for r, s in self.findings.items() if r != role}
        if peers:
            parts.append(
                "COLLEAGUES' VIEWS SO FAR:\n"
                + "\n".join(f"- {r}: {s}" for r, s in peers.items())
            )
        return "\n\n".join(parts)
