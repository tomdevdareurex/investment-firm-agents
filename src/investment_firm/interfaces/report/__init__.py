"""Run-result payloads and self-contained HTML reports (no fastapi dependency)."""

from .html import render_committee_report
from .payload import build_run_result
from .portfolio_html import render_portfolio_report

__all__ = ["build_run_result", "render_committee_report", "render_portfolio_report"]
