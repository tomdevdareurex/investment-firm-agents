"""Notebook opt-in wiring checks; never execute downloads or registry cells."""

import ast
from pathlib import Path

import nbformat
import pytest

import stage2_nb as nb
from fundamentals.build_s07b import SPEC


def _cell_with(cells, text):
    return next(c for c in cells if c.cell_type == "code" and text in c.source)


def test_edgar_builder_wires_all_corrected_evidence_calls():
    assert SPEC["evidence_version"] == "matched-v1"
    assert SPEC["trial_id"] == "S07b-matched-v1"
    cells = nb._cells(SPEC)
    for name in ("dev_sweep", "evaluate", "placebo_test"):
        source = _cell_with(cells, f".{name}(").source
        tree = ast.parse(source)
        call = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == name
        )
        assert any(
            kw.arg == "evidence_version"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "EVIDENCE_VERSION"
            for kw in call.keywords
        )
    for cell in cells:
        if cell.cell_type == "code":
            compile(cell.source, "generated-cell", "exec")
    register = _cell_with(cells, "s2.register_final(").source
    assert "EVIDENCE_VERSION" in register
    assert "DSR dev+val" in register
    assert any(
        "common" in c.source and "development" in c.source.lower() for c in cells
    )


def test_other_builders_keep_legacy_templates_by_default():
    spec = {k: v for k, v in SPEC.items() if k != "evidence_version"}
    cells = nb._cells(spec)
    for text in (nb.SWEEP, nb.EVAL, nb.ROBUST, nb.REGISTER):
        assert any(c.source == text for c in cells)
    assert "EVIDENCE_VERSION" not in _cell_with(cells, "PROTOCOL, REBALANCE").source


def test_unknown_notebook_evidence_version_is_rejected():
    with pytest.raises(ValueError, match="evidence_version"):
        nb._cells({**SPEC, "evidence_version": "typo"})


def test_saved_edgar_calls_match_builder_and_label_retained_legacy_results():
    path = Path(nb.HERE) / SPEC["folder"] / (SPEC["name"] + ".ipynb")
    saved = nbformat.read(path, as_version=4)
    nbformat.validate(saved)
    generated = nb._cells(SPEC)
    for text in (
        "PROTOCOL, REBALANCE",
        ".dev_sweep(",
        ".evaluate(",
        ".placebo_test(",
        "s2.register_final(",
    ):
        assert (
            _cell_with(saved.cells, text).source == _cell_with(generated, text).source
        )
    assert "Legacy outputs" in saved.cells[0].source
    assert "not been rerun" in saved.cells[0].source
    interpretation = next(
        c for c in saved.cells if c.source.startswith("## 11. Interpretation")
    )
    assert "Legacy interpretation" in interpretation.source
