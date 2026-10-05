"""Offline tests for the endpoint registry (config/endpoints.yaml) — no network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from investment_firm import endpoints
from investment_firm.endpoints import EndpointsConfigError

_SRC = Path(endpoints.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _fresh_endpoints(monkeypatch):
    monkeypatch.delenv("IFA_ENDPOINTS_CONFIG", raising=False)
    endpoints.reload_endpoints()
    yield
    endpoints.reload_endpoints()


def _write(tmp_path, text: str) -> Path:
    path = tmp_path / "endpoints.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestShippedConfig:
    def test_loads_and_has_expected_sections(self):
        data = endpoints.load_endpoints()
        for section in ("data", "prediction_markets", "kalshi", "docs", "llm"):
            assert section in data

    def test_every_url_is_https(self):
        data = endpoints.load_endpoints()

        def leaves(node):
            if isinstance(node, dict):
                for value in node.values():
                    yield from leaves(value)
            elif isinstance(node, str):
                yield node

        for section in ("data", "prediction_markets", "docs", "llm"):
            assert all(u.startswith("https://") for u in leaves(data[section]))

    def test_templates_format(self):
        assert endpoints.url("data.ecb", series="X.Y").endswith("/data/X.Y")
        assert "CIK0000320193" in endpoints.url(
            "data.edgar", cik="0000320193", concept="Revenues"
        )

    def test_kalshi_settings_are_usable(self):
        assert "Economics" in endpoints.setting("kalshi.categories")
        assert int(endpoints.setting("kalshi.max_series")) >= 1
        assert int(endpoints.setting("kalshi.max_markets")) >= 1


class TestLookupErrors:
    def test_missing_field_raises(self):
        with pytest.raises(EndpointsConfigError, match="series"):
            endpoints.url("data.ecb")

    def test_unknown_key_raises(self):
        with pytest.raises(EndpointsConfigError, match="unknown endpoint"):
            endpoints.url("data.nope")

    def test_non_url_value_raises(self):
        with pytest.raises(EndpointsConfigError, match="not a URL"):
            endpoints.url("kalshi.categories")


class TestOverride:
    def test_env_override_is_used_and_reloadable(self, tmp_path, monkeypatch):
        path = _write(tmp_path, 'data:\n  ecb: "https://example.test/{series}"\n')
        monkeypatch.setenv("IFA_ENDPOINTS_CONFIG", str(path))
        endpoints.reload_endpoints()
        assert endpoints.url("data.ecb", series="A") == "https://example.test/A"

    def test_non_https_is_rejected(self, tmp_path, monkeypatch):
        path = _write(tmp_path, 'data:\n  ecb: "http://insecure.test/{series}"\n')
        monkeypatch.setenv("IFA_ENDPOINTS_CONFIG", str(path))
        endpoints.reload_endpoints()
        with pytest.raises(EndpointsConfigError, match="https"):
            endpoints.load_endpoints()

    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IFA_ENDPOINTS_CONFIG", str(tmp_path / "absent.yaml"))
        endpoints.reload_endpoints()
        with pytest.raises(EndpointsConfigError, match="not found"):
            endpoints.load_endpoints()


def test_no_url_is_hardcoded_in_source():
    """Every endpoint lives in endpoints.yaml; only help-text placeholders may remain."""
    pattern = re.compile(r"https?://")
    allowed = ("https://<your-workspace-host>",)
    offenders = []
    for path in _SRC.rglob("*.py"):
        if path.name == "endpoints.py":  # the https validator itself
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and not any(a in line for a in allowed):
                offenders.append(f"{path.relative_to(_SRC)}:{lineno}")
    assert not offenders, offenders
