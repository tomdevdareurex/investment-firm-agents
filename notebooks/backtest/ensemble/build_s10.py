"""Build ensemble/sma200_cape.ipynb (S10). Usage: python build_s10.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S10 - SMA200 combined with the CAPE excess yield (ensemble)

**Hypothesis.** SMA200 (trend) and the S01 CAPE excess yield (valuation) use different information:
trend reacts to price, valuation to how expensive equities are versus bonds. If valuation adds
information *conditional on* the trend, a combination should beat SMA200 alone.

| Variant | Equity weight at each monthly check |
|---|---|
| and | 1 if close > SMA200 **and** excess yield > its expanding median, else 0 |
| or | 1 if close > SMA200 **or** excess yield > its expanding median, else 0 |
| avg | 0.5 x SMA200 signal + 0.5 x CAPE signal (0, 0.5 or 1) |

**Inputs and point-in-time lags** (identical to the benchmark and to S01)

| Signal | Source | Lag used |
|---|---|---|
| close vs 200-day SMA | daily S&P 500 price | at the decision close |
| ey = 1 / CAPE - GS10 / 100 vs its expanding median (120-month warm-up, median lagged 1 month) | Shiller monthly | month M usable from M+2 (`bt_pit.RELEASE_LAGS["SHILLER_CAPE"]`) |

Monthly check, next-close execution, 5 bp per unit of turnover. Shiller data end 2024-09, so the
CAPE leg is frozen at its last value afterwards (as in S01).

**Sources.** S01 notebook (`valuation/cape_excess_yield.ipynb`); Asness (2003), *Fight the Fed model*,
SSRN 381480; Faber (2007), *A quantitative approach to tactical asset allocation*.

> Decision-support research only; never places orders."""

DATA = """inputs = {"px": px, "shiller": sample["shiller"][["CAPE", "GS10"]].dropna()}
print("Shiller CAPE/GS10", inputs["shiller"].index[0], "->", inputs["shiller"].index[-1])"""

SIGNAL = """WARMUP_MONTHS = 120
LAG = bt_pit.RELEASE_LAGS["SHILLER_CAPE"]


def cape_signal(inputs):
    m = inputs["shiller"].copy()
    m.index = m.index.to_timestamp(how="start")
    ey = 1.0 / m["CAPE"] - m["GS10"] / 100.0
    median = ey.expanding(min_periods=WARMUP_MONTHS).median().shift(1)
    sig = (ey > median).astype(float).where(median.notna())
    return bt_pit.monthly_to_daily_pit(sig, inputs["px"].index, **LAG)


def build_signal(inputs, combo="and"):
    sma_on, _ = bc.sma_signal(inputs["px"]["close"], 200)
    cape_on = cape_signal(inputs)
    if combo == "and":
        return sma_on * cape_on
    if combo == "or":
        return np.maximum(sma_on, cape_on).where(sma_on.notna() & cape_on.notna())
    return 0.5 * sma_on + 0.5 * cape_on


VARIANTS = {c: dict(combo=c) for c in ("and", "or", "avg")}
PARAMS_TEXT = {n: f"{n}; SMA200 x CAPE excess yield (S01 rule, pit M+2); monthly; next_close; 5bp" for n in VARIANTS}"""

CAVEATS = """* The CAPE leg is the S01 rule unchanged; its long rate before 1953 is Shiller's series, which is
  interpolated from annual data (a small potential look-ahead that S02 avoided by using Moody's AAA).
* S01 alone sat in equities only ~26% of the time, so `and` is a very defensive combination.
* SMA200 itself is the benchmark: a combination can only pass if valuation adds information that the
  trend does not already contain."""

SPEC = dict(
    trial_id="S10",
    strategy="sma200_cape",
    folder="ensemble",
    name="sma200_cape",
    title="S10",
    protocol="main",
    rebalance="monthly",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    caveats_md=CAVEATS,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
