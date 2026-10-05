"""Offline tests for the plain-language glossary."""

from __future__ import annotations

from investment_firm.core.glossary import GLOSSARY, METHODOLOGY, entries, find_terms


def test_every_entry_is_explained():
    for entry in GLOSSARY.values():
        assert entry.plain.strip()
        assert entry.how_calculated.strip()


def test_var_found_by_abbreviation_and_long_form():
    assert GLOSSARY["VaR"] in find_terms("Our 99% VaR is 2%")
    assert GLOSSARY["VaR"] in find_terms("value at risk")


def test_whole_word_matching_only():
    assert GLOSSARY["VaR"] not in find_terms("variance and evaluation")


def test_results_deduplicated_and_in_glossary_order():
    found = find_terms("Sharpe and VaR", "VaR again, Sharpe ratio, max drawdown")
    terms = [e.term for e in found]
    assert len(terms) == len(set(terms))
    order = list(GLOSSARY)
    assert terms == sorted(terms, key=order.index)


def test_empty_input():
    assert find_terms() == []
    assert find_terms("", None) == []


def test_entries_skips_unknown():
    assert [e.term for e in entries(["beta", "nope"])] == ["beta"]


def test_methodology_covers_core_measures():
    text = " ".join(f"{t} {b}" for t, b in METHODOLOGY)
    for needle in ("drawdown", "Sharpe", "252", "√10", "one-bar shift", "yfinance"):
        assert needle in text
