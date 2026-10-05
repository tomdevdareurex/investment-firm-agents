"""Offline tests for the investment-horizon selector (FakeLLM, TestClient — no network)."""

from __future__ import annotations

import pytest

from investment_firm.core.horizon import (
    HORIZONS,
    HorizonError,
    frame_question,
    resolve_horizon,
)
from investment_firm.core.orchestrator import run_committee
from investment_firm.core.planner import plan_roles
from investment_firm.core.roster import RoleSpec

from conftest import openai_text

_VIEW = (
    '{"stance":"BULLISH","conviction":4,"rationale":"Strong",'
    '"key_risks":["risk"],"evidence":["src: data"]}'
)
_SYNTH = '{"recommendation": "HOLD", "summary": "Wait."}'


class TestHorizonDefinitions:
    def test_exactly_three_horizons(self):
        assert list(HORIZONS) == ["short", "medium", "long"]

    @pytest.mark.parametrize(
        "key,period,interval",
        [("short", "1y", "1d"), ("medium", "max", "1wk"), ("long", "max", "1mo")],
    )
    def test_chart_mapping(self, key, period, interval):
        hz = HORIZONS[key]
        assert (hz.chart_period, hz.chart_interval) == (period, interval)

    def test_frame_question_appends_marker(self):
        framed = frame_question("Q?", "long")
        assert framed.startswith("Q?")
        assert "Investment horizon: Long term" in framed
        assert "'max'" in framed

    def test_unknown_horizon_raises(self):
        with pytest.raises(HorizonError):
            frame_question("Q?", "decade")
        with pytest.raises(HorizonError):
            resolve_horizon("decade")

    def test_default_is_short(self):
        assert resolve_horizon(None).key == "short"
        assert resolve_horizon("").key == "short"


class TestHorizonInCommittee:
    def test_every_agent_sees_framed_question_and_memo_keeps_raw(self, fake_llm):
        llm = fake_llm([openai_text(_VIEW)] * 3 + [openai_text(_SYNTH)])
        memo, _ = run_committee("Q?", profile="budget", simple=True, horizon="long")
        llm.assert_call_count(4)
        for _, messages, _ in llm.calls:
            user = " ".join(m["content"] for m in messages if m["role"] == "user")
            assert "Investment horizon: Long term" in user
        assert memo.question == "Q?"
        assert memo.horizon == "long"
        assert "Horizon:  long" in memo.render()

    def test_unknown_horizon_rejected_before_any_call(self, fake_llm):
        llm = fake_llm([])
        with pytest.raises(HorizonError):
            run_committee("Q?", profile="budget", simple=True, horizon="decade")
        llm.assert_call_count(0)

    def test_planner_gets_long_horizon_hint(self, fake_llm):
        llm = fake_llm([openai_text('{"plan": ["strategist"], "reasoning": "x"}')])
        spec = RoleSpec(
            name="strategist", group="g", tier="SENIOR", model="m", mandate="M."
        )
        planner = RoleSpec(name="cio", group="g", tier="HEAD", model="m", mandate="P.")
        chosen = plan_roles(frame_question("Q?", "long"), [spec], planner)
        assert chosen == ["strategist"]
        assert "long horizon" in llm.calls[0][1][-1]["content"]

    def test_planner_short_horizon_hint(self, fake_llm):
        llm = fake_llm([openai_text('{"plan": ["strategist"]}')])
        spec = RoleSpec(
            name="strategist", group="g", tier="SENIOR", model="m", mandate="M."
        )
        plan_roles(frame_question("Q?", "short"), [spec], spec)
        assert "short horizon" in llm.calls[0][1][-1]["content"]


fastapi = pytest.importorskip("fastapi")

from test_web_runs import _wait_for_done, client  # noqa: E402,F401


class TestHorizonWeb:
    def test_run_echoes_horizon(self, client):  # noqa: F811
        post = client.post("/api/runs", json={"question": "x", "horizon": "medium"})
        assert post.status_code == 202
        data = _wait_for_done(client, post.json()["run_id"])
        assert data["horizon"] == "medium"
        assert data["result"]["horizon"] == "medium"
        assert data["result"]["horizon_label"] == HORIZONS["medium"].label
        listed = client.get("/api/runs").json()["runs"]
        assert listed[0]["horizon"] == "medium"

    def test_invalid_horizon_is_422(self, client):  # noqa: F811
        resp = client.post("/api/runs", json={"question": "x", "horizon": "decade"})
        assert resp.status_code == 422

    def test_preview_echoes_horizon_label(self, client):  # noqa: F811
        data = client.get("/api/preview?horizon=long").json()
        assert data["horizon"] == "long"
        assert data["horizon_label"] == "Long term (3+ years)"
        assert client.get("/api/preview?horizon=decade").status_code == 422


# Existing static string-literal uses in app.js (loadProfiles / loadBackend).
_APP_JS_INNERHTML_BASELINE = 4


class TestHorizonStatic:
    def test_index_has_radio_group(self, client):  # noqa: F811
        html = client.get("/").text
        assert html.count('name="horizon"') == 3
        assert 'id="horizon-group"' in html

    def test_charts_js_maps_horizons(self, client):  # noqa: F811
        js = client.get("/static/charts.js").text
        assert "ifa:horizon" in js and "'1wk'" in js and "'1mo'" in js

    def test_app_js_wires_horizon_without_new_html_sinks(self, client):  # noqa: F811
        js = client.get("/static/app.js").text
        assert "selectedHorizon" in js and "ifa:horizon" in js
        assert js.count(".innerHTML") <= _APP_JS_INNERHTML_BASELINE
        assert "insertAdjacentHTML" not in js

    def test_memo_js_is_served_and_xss_safe(self, client):  # noqa: F811
        resp = client.get("/static/memo.js")
        assert resp.status_code == 200
        assert "renderMemoTab" in resp.text
        assert ".innerHTML" not in resp.text
        assert "insertAdjacentHTML" not in resp.text
