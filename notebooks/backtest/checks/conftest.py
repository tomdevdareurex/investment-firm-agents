"""Pytest setup for notebooks/backtest/checks: make the sibling bt_* modules importable."""

import sys
from pathlib import Path

BT_DIR = Path(__file__).resolve().parents[1]
if str(BT_DIR) not in sys.path:
    sys.path.insert(0, str(BT_DIR))
