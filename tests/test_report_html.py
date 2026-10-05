"""Offline tests for the run-result payload and the committee HTML report."""

from __future__ import annotations

import pytest

import investment_firm
from investment_firm.core.schemas import Source
from investment_firm.interfaces.report import build_run_result, render_committee_report

from conftest import openai_text
from test_web_runs import _make_memo, _make_tracker

HEADINGS = [
    "Investment Committee Report",
    "In plain words",
    "Why the committee thinks so",
    "What could go wrong",
    "What to watch",
    "How each specialist saw it",
    "Bull vs Bear debate",
    "Research briefing",
    "Sources",
    "Warnings and data gaps",
    "Cost of this analysis",
    "Glossary",
    "How the numbers are calculated",
]


def _payload(**memo_updates):
    memo = _make_memo()
    memo = memo.model_copy(
        update={
            "headline": "Steady monthly buying looks reasonable.",
            "key_reasons": ["Earnings are growing."],
            "main_risks": ["A fall of 20% would not be unusual."],
            "what_to_watch": ["Inflation data."],
            "confidence": 3,
            **memo_updates,
        }
    )
    return build_run_result(memo, _make_tracker(), horizon="long", run_id="abc")


class TestBuildRunResult:
    def test_new_keys(self):
        result = _payload()
        assert result["report_url"] == "/api/runs/abc/report.html"
        assert result["horizon"] == "long"
        assert result["horizon_label"] == "Long term (3+ years)"
        assert result["recommendation_plain"].startswith("Favourable")
        assert result["stance_plain"]["BEARISH"].startswith("Negative")
        assert isinstance(result["glossary"], list)
        assert result["confidence"] == 3
        assert result["key_reasons"] == ["Earnings are growing."]

    def test_glossary_picks_up_used_jargon(self):
        terms = [g["term"] for g in _payload()["glossary"]]
        assert "credit spread" in terms  # credit_analyst rationale: "Spreads stable"
        assert "VaR" not in terms

    def test_no_run_id_means_no_report_url(self):
        result = build_run_result(_make_memo(), _make_tracker())
        assert result["report_url"] == ""


class TestRenderCommitteeReport:
    def test_structure_and_safety(self):
        html_text = render_committee_report(_payload())
        assert html_text.startswith("<!DOCTYPE html>")
        for heading in HEADINGS:
            assert heading in html_text, heading
        assert investment_firm.DISCLAIMER in html_text
        assert "Long term" in html_text
        assert "<script" not in html_text
        assert 'rel="noopener noreferrer"' in html_text

    def test_headings_in_order(self):
        html_text = render_committee_report(_payload())
        positions = [html_text.index(h) for h in HEADINGS]
        assert positions == sorted(positions)

    def test_xss_payloads_are_escaped(self):
        memo = _make_memo()
        memo.views[0].rationale = "<script>alert(1)</script>"
        memo.web_sources = [Source(url="javascript:alert(1)", title="evil")]
        html_text = render_committee_report(
            build_run_result(memo, _make_tracker(), run_id="x")
        )
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text
        assert "<script" not in html_text
        assert 'href="javascript:' not in html_text

    def test_old_payload_without_new_keys_renders(self):
        result = _payload()
        for key in (
            "headline",
            "key_reasons",
            "main_risks",
            "what_to_watch",
            "confidence",
            "glossary",
            "horizon",
            "horizon_label",
            "recommendation_plain",
            "stance_plain",
            "generated_at",
        ):
            result.pop(key)
        html_text = render_committee_report(result)
        assert "(not available)" in html_text
        assert "How the numbers are calculated" in html_text

    def test_empty_payload_renders(self):
        assert "Investment Committee Report" in render_committee_report({})


fastapi = pytest.importorskip("fastapi")

from test_web_runs import _wait_for_done, client, error_client  # noqa: E402,F401


class TestReportRoute:
    def test_done_run_downloads_attachment(self, client):  # noqa: F811
        run_id = client.post("/api/runs", json={"question": "Q?"}).json()["run_id"]
        data = _wait_for_done(client, run_id)
        assert data["result"]["report_url"] == f"/api/runs/{run_id}/report.html"
        resp = client.get(f"/api/runs/{run_id}/report.html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        disposition = resp.headers["content-disposition"]
        assert "attachment" in disposition and "ic-report-" in disposition
        assert "Investment Committee Report" in resp.text

    def test_unknown_run_404(self, client):  # noqa: F811
        assert client.get("/api/runs/nope/report.html").status_code == 404

    def test_error_run_409(self, error_client):  # noqa: F811
        run_id = error_client.post("/api/runs", json={"question": "Q?"}).json()[
            "run_id"
        ]
        _wait_for_done(error_client, run_id)
        assert error_client.get(f"/api/runs/{run_id}/report.html").status_code == 409


class TestCliReport:
    _VIEW = (
        '{"stance":"BULLISH","conviction":4,"rationale":"Strong",'
        '"key_risks":["risk"],"evidence":["src: data"]}'
    )

    def test_cli_writes_report(self, fake_llm, tmp_path, capsys):
        from investment_firm.interfaces.cli import main

        fake_llm(
            [openai_text(self._VIEW)] * 3
            + [openai_text('{"recommendation": "HOLD", "summary": "Wait."}')]
        )
        out = tmp_path / "r.html"
        code = main(
            ["Q?", "--simple", "--no-stream", "--horizon", "long", "--report", str(out)]
        )
        assert code == 0
        text = out.read_text(encoding="utf-8")
        assert "Investment Committee Report" in text
        assert "Long term" in text
        assert "[report] written to" in capsys.readouterr().out

    def test_cli_report_write_failure_returns_1(self, fake_llm, tmp_path):
        from investment_firm.interfaces.cli import main

        fake_llm(
            [openai_text(self._VIEW)] * 3
            + [openai_text('{"recommendation": "HOLD", "summary": "Wait."}')]
        )
        bad = tmp_path / "missing-dir" / "r.html"
        assert main(["Q?", "--simple", "--no-stream", "--report", str(bad)]) == 1
