"""Layout guarantees for the data/ package move.

1. Old ``investment_firm.core.*`` import paths keep working (re-export shims).
2. The shims expose the *same objects* as the new ``investment_firm.data.*`` modules.
3. ``data/`` never imports from ``core/`` or ``interfaces/`` (layering rule).
"""

from __future__ import annotations

import sys


def test_core_risk_shim_reexports_same_objects():
    import investment_firm.core.risk as old
    import investment_firm.data.risk as new

    assert old.__all__, "shim must declare its re-exports"
    for name in old.__all__:
        assert getattr(old, name) is getattr(new, name), name


def test_core_indicators_shim_reexports_same_objects():
    import investment_firm.core.indicators as old
    import investment_firm.data.indicators as new

    assert old.__all__, "shim must declare its re-exports"
    for name in old.__all__:
        assert getattr(old, name) is getattr(new, name), name


def test_data_package_does_not_import_core_or_interfaces():
    before = {m for m in sys.modules if m.startswith("investment_firm.")}
    import investment_firm.data.risk  # noqa: F401

    loaded = {
        m
        for m in sys.modules
        if m.startswith(("investment_firm.core", "investment_firm.interfaces"))
        and m not in before
    }
    assert not loaded, f"data/ pulled in higher layers: {sorted(loaded)}"
