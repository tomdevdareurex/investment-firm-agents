"""Offline tests for the committee vote tally (core/vote.py)."""

from __future__ import annotations

from investment_firm.core.roster import RoleSpec, load_firm
from investment_firm.core.schemas import AnalystView
from investment_firm.core.vote import TIE, VoteResult, render_vote, tally


def _spec(name, *, votes=True, weight=1, veto=False):
    return RoleSpec(
        name=name,
        group="g",
        tier="WORKER",
        model="m",
        mandate="",
        votes=votes,
        vote_weight=weight,
        veto=veto,
    )


def _view(role, stance, conviction=3, error=""):
    return AnalystView(
        role=role,
        model="m",
        stance=stance,
        conviction=conviction,
        rationale="r",
        error=error,
    )


SPECS = {
    "portfolio_manager": _spec("portfolio_manager", weight=3),
    "strategist": _spec("strategist", weight=2),
    "equity_analyst": _spec("equity_analyst", weight=1),
    "market_risk": _spec("market_risk", weight=2, veto=True),
    "compliance": _spec("compliance", votes=False, weight=0, veto=True),
    "economist": _spec("economist", votes=False),
}

CFG = {
    "tally_rule": "weighted_majority_of_stance",
    "veto_roles": ["compliance", "market_risk"],
    "veto_min_conviction": 3,
}


class TestTally:
    def test_weights_sum_and_winner(self):
        views = [
            _view("portfolio_manager", "BULLISH"),
            _view("strategist", "BEARISH"),
            _view("equity_analyst", "BEARISH"),
        ]
        res = tally(views, SPECS, CFG)
        assert res.totals["BULLISH"] == 3.0
        assert res.totals["BEARISH"] == 3.0
        assert res.winner == TIE
        assert res.margin == 0
        assert res.participants == 3
        assert res.excluded == []

        views.append(_view("market_risk", "BULLISH", conviction=2))
        res = tally(views, SPECS, CFG)
        assert res.winner == "BULLISH"
        assert res.margin == 2.0
        assert res.veto is False

    def test_error_and_non_voting_excluded(self):
        views = [
            _view("portfolio_manager", "BULLISH"),
            _view("strategist", "ERROR", conviction=0, error="API error: boom"),
            _view("economist", "BEARISH"),
            _view("unknown_role", "BEARISH"),
        ]
        res = tally(views, SPECS, CFG)
        assert res.participants == 1
        assert set(res.excluded) == {"strategist", "economist", "unknown_role"}
        assert res.winner == "BULLISH"
        notes = {r.role: r.note for r in res.rows}
        assert "ERROR" in notes["strategist"]
        assert "non-voting" in notes["economist"]
        assert "not in roster" in notes["unknown_role"]
        assert all(isinstance(r.counted, bool) for r in res.rows)

    def test_veto_threshold(self):
        base = [_view("portfolio_manager", "BULLISH", conviction=5)]
        low = tally(base + [_view("market_risk", "BEARISH", 2)], SPECS, CFG)
        assert low.veto is False
        high = tally(base + [_view("market_risk", "BEARISH", 3)], SPECS, CFG)
        assert high.veto is True
        assert high.veto_by == ["market_risk"]
        row = next(r for r in high.rows if r.role == "market_risk")
        assert "VETO" in row.note

    def test_non_voting_veto_role_still_vetoes(self):
        views = [
            _view("portfolio_manager", "BULLISH", conviction=5),
            _view("compliance", "BEARISH", conviction=4),
        ]
        res = tally(views, SPECS, CFG)
        assert res.veto is True
        assert res.veto_by == ["compliance"]
        # compliance does not vote, so totals unaffected
        assert res.totals["BEARISH"] == 0.0
        assert "compliance" in res.excluded

    def test_error_view_from_veto_role_does_not_veto(self):
        views = [
            _view("market_risk", "ERROR", conviction=0, error="x"),
        ]
        res = tally(views, SPECS, CFG)
        assert res.veto is False
        assert res.winner == TIE

    def test_empty(self):
        res = tally([], SPECS, CFG)
        assert res.winner == TIE
        assert res.participants == 0
        assert res.totals == {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}

    def test_defaults_without_cfg(self):
        views = [_view("market_risk", "BEARISH", conviction=3)]
        res = tally(views, SPECS, None)
        assert res.rule == "weighted_majority_of_stance"
        assert res.veto_min_conviction == 3
        assert res.veto is True  # spec.veto=True suffices

    def test_zero_weight_voter_counts_as_one(self):
        specs = {"a": _spec("a", weight=0)}
        res = tally([_view("a", "NEUTRAL")], specs, CFG)
        assert res.totals["NEUTRAL"] == 1.0
        assert res.winner == "NEUTRAL"

    def test_to_dict_json_safe(self):
        import json

        res = tally([_view("portfolio_manager", "BULLISH")], SPECS, CFG)
        data = res.to_dict()
        json.dumps(data)
        assert data["winner"] == "BULLISH"
        assert data["rows"][0]["role"] == "portfolio_manager"

    def test_firm_yaml_committee_block(self):
        firm = load_firm()
        committee = firm.get("committee") or {}
        assert committee.get("veto_min_conviction") == 3
        assert "market_risk" in committee.get("veto_roles", [])


class TestRender:
    def test_render_mentions_totals_outcome_and_rows(self):
        views = [
            _view("portfolio_manager", "BULLISH", conviction=4),
            _view("market_risk", "BEARISH", conviction=3),
        ]
        text = render_vote(tally(views, SPECS, CFG))
        assert "Totals: BULLISH 3 | BEARISH 2 | NEUTRAL 0" in text
        assert "Outcome: BULLISH by a margin of 1" in text
        assert "VETO raised by: market_risk" in text
        assert "- portfolio_manager: BULLISH (conviction 4, weight 3, counted)" in text
        assert "cannot be BUY" in text

    def test_render_tie(self):
        text = render_vote(VoteResult())
        assert "Outcome: TIE" in text
        assert "VETO" not in text
