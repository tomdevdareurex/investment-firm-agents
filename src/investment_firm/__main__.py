"""Enable ``python -m investment_firm``."""
from __future__ import annotations

from .interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
