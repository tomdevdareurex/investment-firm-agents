"""A11 step 0 - dump raw inputs for the independent replication.

Only data loaders are used here (bt_long); the replication itself
(rep_independent.py) touches no bt_common / bt_periods / stage2 code.
"""

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import bt_long  # noqa: E402

OUT = HERE / "rep_inputs.pkl"

if __name__ == "__main__":
    s = bt_long.long_sample()
    px, cash, shiller = s["px"], s["cash"], s["shiller"]
    vix = bt_long.fred_series("VIXCLS")
    vix3m = bt_long.fred_series("VXVCLS")
    print("px cols", list(px.columns), px.index[0].date(), px.index[-1].date())
    print("cash", type(cash), getattr(cash, "name", None), cash.index[0].date())
    print("shiller cols", list(shiller.columns), shiller.index[0], shiller.index[-1])
    print("vix", vix.index[0].date(), "vix3m", vix3m.index[0].date())
    pd.to_pickle(dict(px=px, cash=cash, shiller=shiller, vix=vix, vix3m=vix3m), OUT)
    print("wrote", OUT)
