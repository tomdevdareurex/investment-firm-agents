"""Free, keyless alternative-data tools (QuiverQuant substitutes).

QuiverQuant is a paid service whose terms forbid scraping, so the same signal
families are sourced from the primary, public, keyless US government APIs:

  - ``get_gov_contracts``  — federal contract awards, USAspending.gov (api v2).
  - ``get_lobbying``       — lobbying disclosures, U.S. Senate LDA API.
  - ``get_insider_trades`` — recent SEC Form 4 filings, EDGAR full-text search.

Same contract as :mod:`datasources`: every tool is *read-only* and returns a
**provenance-tagged** dict (``source``, ``as_of``). HTTP goes through ``requests``
from the optional ``.[data]`` extra, imported lazily. The helpers shared with
:mod:`datasources` are imported inside the functions so that module can register
these tools without an import cycle.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .base import Tool, ToolError
from ... import endpoints

_MAX_LIMIT = 25
_FORM4_LOOKBACK_DAYS = 180


def _helpers():
    from . import datasources as ds

    return ds


def _clamp_limit(limit: Any) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(_MAX_LIMIT, value))


def _edgar_headers() -> Dict[str, str]:
    """EDGAR requires a descriptive User-Agent; mirror :func:`get_company_filing`."""
    user_agent = (
        os.getenv("SEC_USER_AGENT", "").strip()
        or "investment-firm-agents (educational; contact: user)"
    )
    return {"User-Agent": user_agent, "Accept": "application/json"}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- USAspending.gov: federal contract awards ------------------------------


def get_gov_contracts(
    recipient: str, limit: int = 10, fiscal_year: Optional[int] = None
) -> dict:
    """Return the largest recent federal contract awards to ``recipient``.

    Searches USAspending.gov (``spending_by_award``, contract types A-D) by
    recipient name for the given US fiscal year (default: the current one,
    Oct-Sep). Keyless. Values are USD obligations, not revenue recognised.
    """
    ds = _helpers()
    requests = ds._require("requests")  # type: ignore
    name = str(recipient or "").strip()
    if not name:
        raise ToolError("recipient must be a non-empty company name")
    limit = _clamp_limit(limit)
    today = date.today()
    if fiscal_year:
        fy = int(fiscal_year)
    else:
        fy = today.year + (1 if today.month >= 10 else 0)
    body = {
        "filters": {
            "recipient_search_text": [name],
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [
                {"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}
            ],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Start Date",
            "End Date",
            "Description",
        ],
        "limit": limit,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
    }
    resp = requests.post(
        endpoints.url("data.usaspending_awards"), json=body, timeout=30
    )
    if resp.status_code != 200:
        raise ds._http_error("USAspending", resp)
    data = ds._json_or_error("USAspending", resp)
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ToolError("could not parse USAspending response")
    awards: List[Dict[str, Any]] = []
    total = 0.0
    for row in rows[:limit]:
        amount = _to_float(row.get("Award Amount"))
        total += amount or 0.0
        awards.append(
            {
                "award_id": row.get("Award ID"),
                "recipient": row.get("Recipient Name"),
                "amount_usd": amount,
                "agency": row.get("Awarding Agency"),
                "start": row.get("Start Date"),
                "end": row.get("End Date"),
                "description": (str(row.get("Description") or ""))[:200],
            }
        )
    return {
        "recipient": name,
        "fiscal_year": fy,
        "count": len(awards),
        "total_amount_usd": round(total, 2),
        "awards": awards,
        "source": "USAspending.gov (api v2 spending_by_award)",
        "as_of": ds._now_iso(),
        "caveat": (
            "obligated contract values for one fiscal year, matched by recipient "
            "name; subsidiaries may file under other names"
        ),
    }


# --- U.S. Senate LDA: lobbying disclosures --------------------------------


def _lda_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    key = os.getenv("SENATE_LDA_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Token {key}"
    return headers


def get_lobbying(client_name: str, limit: int = 10) -> dict:
    """Return the most recent lobbying filings where ``client_name`` is the client.

    U.S. Senate Lobbying Disclosure Act API, keyless (15 requests/min anonymous;
    set ``SENATE_LDA_API_KEY`` for 120/min). ``income`` is what the registrant
    (lobbying firm) reported; ``expenses`` is what an in-house filer reported.
    """
    ds = _helpers()
    requests = ds._require("requests")  # type: ignore
    name = str(client_name or "").strip()
    if not name:
        raise ToolError("client_name must be a non-empty company name")
    limit = _clamp_limit(limit)
    resp = requests.get(
        endpoints.url("data.senate_lda_filings"),
        params={"client_name": name, "page_size": limit, "ordering": "-dt_posted"},
        headers=_lda_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise ds._http_error("Senate LDA", resp)
    data = ds._json_or_error("Senate LDA", resp)
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ToolError("could not parse Senate LDA response")
    filings: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        registrant = row.get("registrant") or {}
        client = row.get("client") or {}
        issues: List[str] = []
        for act in row.get("lobbying_activities") or []:
            label = act.get("general_issue_code_display") or act.get(
                "general_issue_code"
            )
            if label and label not in issues:
                issues.append(str(label))
        filings.append(
            {
                "filing_year": row.get("filing_year"),
                "period": row.get("filing_period_display") or row.get("filing_period"),
                "type": row.get("filing_type_display") or row.get("filing_type"),
                "registrant": registrant.get("name"),
                "client": client.get("name"),
                "income_usd": _to_float(row.get("income")),
                "expenses_usd": _to_float(row.get("expenses")),
                "posted": row.get("dt_posted"),
                "issues": issues[:5],
            }
        )
    return {
        "client": name,
        "count": len(filings),
        "total_reported": data.get("count"),
        "filings": filings,
        "source": "U.S. Senate Lobbying Disclosure Act API",
        "as_of": ds._now_iso(),
        "note": "anonymous: 15 req/min; set SENATE_LDA_API_KEY for 120/min",
    }


# --- SEC EDGAR full-text search: Form 4 insider filings --------------------


def _parse_display_name(label: str) -> Dict[str, str]:
    """Split ``"Cook Timothy D  (CIK 0001214156)"`` into name and CIK."""
    text = str(label or "")
    match = re.search(r"\(CIK\s+(\d+)\)", text)
    cik = match.group(1) if match else ""
    name = re.sub(r"\s*\(CIK\s+\d+\)\s*$", "", text).strip()
    return {"name": name, "cik": cik}


def get_insider_trades(ticker_or_cik: str, limit: int = 10) -> dict:
    """List recent SEC Form 4 (insider transaction) filings for a company.

    Uses EDGAR full-text search over the last 180 days. It reports *filing
    events* (who filed, when, link); the buy/sell direction and size require
    opening the filing, so this is an activity indicator, not a position table.
    """
    ds = _helpers()
    requests = ds._require("requests")  # type: ignore
    key = str(ticker_or_cik or "").strip()
    if not key:
        raise ToolError("ticker_or_cik must be a ticker symbol or CIK")
    limit = _clamp_limit(limit)
    today = date.today()
    start = today - timedelta(days=_FORM4_LOOKBACK_DAYS)
    params = {
        "q": f'"{key.upper()}"',
        "forms": "4",
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": today.isoformat(),
    }
    resp = requests.get(
        endpoints.url("data.edgar_fts"),
        params=params,
        headers=_edgar_headers(),
        timeout=30,
    )
    if resp.status_code != 200:
        raise ds._http_error("EDGAR full-text search", resp)
    data = ds._json_or_error("EDGAR full-text search", resp)
    hits = ((data or {}).get("hits") or {}).get("hits")
    if not isinstance(hits, list):
        raise ToolError("could not parse EDGAR full-text search response")
    filings: List[Dict[str, Any]] = []
    for hit in hits[:limit]:
        src = hit.get("_source") or {}
        names = [_parse_display_name(n) for n in src.get("display_names") or []]
        ciks = [str(c) for c in src.get("ciks") or []]
        adsh = str(src.get("adsh") or "")
        # The issuer is the display name whose CIK is the last listed CIK; the
        # remaining names are the reporting insiders.
        issuer_cik = ciks[-1] if ciks else ""
        reporters = [n["name"] for n in names if n["cik"] != issuer_cik]
        issuer = next((n["name"] for n in names if n["cik"] == issuer_cik), "")
        url = ""
        if adsh and issuer_cik:
            url = endpoints.url(
                "data.edgar_archives",
                cik=issuer_cik.lstrip("0") or issuer_cik,
                accession=adsh.replace("-", ""),
            )
        filings.append(
            {
                "filed": src.get("file_date"),
                "period": src.get("period_ending"),
                "form": src.get("form") or "4",
                "issuer": issuer,
                "reporters": reporters,
                "accession": adsh,
                "url": url,
            }
        )
    return {
        "query": key.upper(),
        "lookback_days": _FORM4_LOOKBACK_DAYS,
        "count": len(filings),
        "total_hits": (((data or {}).get("hits") or {}).get("total") or {}).get(
            "value"
        ),
        "filings": filings,
        "source": "SEC EDGAR Form 4 (full-text search)",
        "as_of": ds._now_iso(),
        "caveat": (
            "ownership direction and size require reading the filing; this lists "
            "recent Form 4 events only"
        ),
    }


# --- Registry assembly ----------------------------------------------------

_GOV_CONTRACTS_TOOL = Tool(
    name="get_gov_contracts",
    description=(
        "Get the largest US federal contract awards to a company for a fiscal year "
        "(USAspending.gov, keyless). Use to gauge government-revenue exposure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "company name as it appears in federal awards",
            },
            "limit": {"type": "integer", "description": "1-25 awards", "default": 10},
            "fiscal_year": {
                "type": "integer",
                "description": "US fiscal year (Oct-Sep); default current",
            },
        },
        "required": ["recipient"],
    },
    func=get_gov_contracts,
)

_LOBBYING_TOOL = Tool(
    name="get_lobbying",
    description=(
        "Get recent US federal lobbying disclosures filed on behalf of a company "
        "(Senate LDA API, keyless): registrant, reported income/expenses, issues."
    ),
    parameters={
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "company name"},
            "limit": {"type": "integer", "description": "1-25 filings", "default": 10},
        },
        "required": ["client_name"],
    },
    func=get_lobbying,
)

_INSIDER_TRADES_TOOL = Tool(
    name="get_insider_trades",
    description=(
        "List recent SEC Form 4 insider-transaction filings (last 180 days) for a "
        "ticker or CIK via EDGAR full-text search. Activity indicator with filing "
        "links; direction/size are inside the filing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ticker_or_cik": {"type": "string", "description": "e.g. 'AAPL'"},
            "limit": {"type": "integer", "description": "1-25 filings", "default": 10},
        },
        "required": ["ticker_or_cik"],
    },
    func=get_insider_trades,
)


def default_altdata_tools() -> List[Tool]:
    """Free, keyless alt-data tools (appended to :func:`default_data_tools`)."""
    return [_GOV_CONTRACTS_TOOL, _LOBBYING_TOOL, _INSIDER_TRADES_TOOL]
