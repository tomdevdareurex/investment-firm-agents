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

    def test_failure_reason_and_fallback_note(self):
        result = _payload(
            recommendation="ERROR",
            failure_reason="empty response",
            synth_note="claude-5.5-opus failed (empty response); fallback x also failed.",
        )
        assert result["failure_reason"] == "empty response"
        assert any("fallback x also failed" in w for w in result["warnings"])
        html_text = render_committee_report(result)
        assert "Why there is no ruling:" in html_text
        assert "empty response" in html_text


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


_VOTE = {
    "rows": [
        {
            "role": "portfolio_manager",
            "model": "m",
            "stance": "BULLISH",
            "conviction": 4,
            "weight": 3.0,
            "counted": True,
            "note": "",
        },
        {
            "role": "compliance_officer",
            "model": "m",
            "stance": "BEARISH",
            "conviction": 4,
            "weight": 0.0,
            "counted": False,
            "note": "non-voting veto role",
        },
    ],
    "totals": {"BULLISH": 3.0, "BEARISH": 0.0, "NEUTRAL": 0.0},
    "winner": "BULLISH",
    "margin": 3.0,
    "veto": True,
    "veto_by": ["compliance_officer"],
    "participants": 1,
    "excluded": ["compliance_officer"],
    "rule": "weighted_majority_of_stance",
    "veto_min_conviction": 3,
}


class TestVoteSurfaces:
    def test_payload_carries_vote(self):
        assert _payload()["vote"] == {}
        assert _payload(vote=_VOTE)["vote"]["winner"] == "BULLISH"

    def test_html_vote_section(self):
        html_text = render_committee_report(_payload(vote=_VOTE))
        assert "Committee vote (advisory)" in html_text
        assert "VETO raised by compliance_officer" in html_text
        assert "BULLISH 3 |" in html_text
        assert "<script" not in html_text
        assert html_text.index("Bull vs Bear debate") < html_text.index(
            "Committee vote (advisory)"
        ) < html_text.index("Research briefing")

    def test_html_without_vote_has_no_section(self):
        assert "Committee vote" not in render_committee_report(_payload())

    def test_vote_xss_escaped(self):
        bad = dict(_VOTE, winner="<img src=x onerror=alert(1)>")
        html_text = render_committee_report(_payload(vote=bad))
        assert "<img" not in html_text
        assert "&lt;img" in html_text


_CROSS_CHECK = {
    "status": "ok",
    "model": "gpt-5.6-terra",
    "agrees": False,
    "concerns": ["Valuation looks stretched.", "<b>bold</b> concern"],
    "note": "The bear case is under-weighted.",
}


class TestCrossCheckSurfaces:
    def test_payload_carries_cross_check(self):
        assert _payload()["cross_check"] == {}
        assert _payload(cross_check=_CROSS_CHECK)["cross_check"]["agrees"] is False

    def test_html_cross_check_section_after_vote(self):
        html_text = render_committee_report(
            _payload(vote=_VOTE, cross_check=_CROSS_CHECK)
        )
        assert "Second opinion (CIO cross-check)" in html_text
        assert "Disagrees" in html_text
        assert "gpt-5.6-terra" in html_text
        assert "Valuation looks stretched." in html_text
        assert "<b>bold</b>" not in html_text and "&lt;b&gt;bold" in html_text
        assert html_text.index("Committee vote (advisory)") < html_text.index(
            "Second opinion (CIO cross-check)"
        ) < html_text.index("Research briefing")

    def test_html_cross_check_error_and_skipped(self):
        err = {"status": "error", "model": "m", "reason": "API error: boom"}
        html_text = render_committee_report(_payload(cross_check=err))
        assert "Second opinion unavailable" in html_text
        assert "API error: boom" in html_text
        skipped = {"status": "skipped", "reason": "budget"}
        assert "Second opinion" not in render_committee_report(
            _payload(cross_check=skipped)
        )
        assert "Second opinion" not in render_committee_report(_payload())


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
