"""Build trend/tsmom.ipynb (S05). Usage: python build_s05.py [--execute]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stage2_nb  # noqa: E402

HEADER = """# S05 - Time-series momentum (trend)

**Hypothesis.** Asset returns are positively autocorrelated at 3-12 month horizons
(Moskowitz, Ooi & Pedersen 2012). Holding the S&P 500 only when its own trailing excess
return is positive captures this and sidesteps long bear markets, with a different
lookback structure than the price-vs-SMA200 rule.

| Variant | Risk-on (hold S&P 500) when ... |
|---|---|
| m12_skip1 | total return from t-12m to t-1m > T-bill accrual over the same window |
| m12 | total return over the last 12 months > T-bill accrual |
| m6 | total return over the last 6 months > T-bill accrual |

**Inputs and point-in-time lags**

| Series | Source | Lag used |
|---|---|---|
| S&P 500 daily total return, T-bill daily return | `bt_long.long_sample` | up to the decision close; 21 trading days per month; next-close fill |

Monthly check, next-close execution, 5 bp per switch.

**Sources.** Moskowitz, Ooi & Pedersen (2012), *Time series momentum*, JFE, SSRN 2089463;
Hurst, Ooi & Pedersen (2017), *A century of evidence on trend-following investing*, SSRN 2993026;
Zakamulin (2015), *Market timing with moving averages*, SSRN 2585056.

> Decision-support research only; never places orders."""

DATA = """inputs = {"px": px, "cash": cash}
print("daily TR and T-bill returns", px.index[0].date(), "->", px.index[-1].date())"""

SIGNAL = """M = 21  # trading days per month


def build_signal(inputs, look=12, skip=0):
    tr = inputs["px"]["tr_close"]
    ci = (1 + inputs["cash"].reindex(tr.index).fillna(0.0)).cumprod()
    a, b = look * M, skip * M
    excess = (tr.shift(b) / tr.shift(a) - 1) - (ci.shift(b) / ci.shift(a) - 1)
    return (excess > 0).astype(float).where(excess.notna())


VARIANTS = {"m12_skip1": dict(look=12, skip=1), "m12": dict(look=12), "m6": dict(look=6)}
PARAMS_TEXT = {n: f"{n}; trailing TR minus T-bill accrual > 0; monthly; next_close; 5bp" for n in VARIANTS}"""

CAVEATS = """* Closely related to SMA200 (both are trend rules on the same index), so a large Sharpe difference
  between them is not expected; the bootstrap test against SMA200 is demanding here.
* 21 trading days per month is an approximation of calendar months.
* Single asset: the diversification benefit behind published TSMOM results (many markets) is absent."""

SPEC = dict(
    trial_id="S05",
    strategy="tsmom",
    folder="trend",
    name="tsmom",
    title="S05",
    protocol="main",
    rebalance="monthly",
    header_md=HEADER,
    data_code=DATA,
    signal_code=SIGNAL,
    caveats_md=CAVEATS,
)

if __name__ == "__main__":
    stage2_nb.main(SPEC)
