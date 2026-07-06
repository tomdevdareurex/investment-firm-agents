"""Web interface (FastAPI) for the investment-firm-agents preview UI.

Requires the ``.[api]`` extra::

    .venv\\Scripts\\python.exe -m pip install -e ".[api]"

Then run::

    .venv\\Scripts\\python.exe -m uvicorn investment_firm.interfaces.web.app:app

Guard: importing this package without fastapi installed raises a clear
RuntimeError with install instructions rather than a cryptic ImportError.
"""

from __future__ import annotations

try:
    import fastapi  # noqa: F401
except ImportError as _exc:
    raise RuntimeError(
        "The web interface requires the 'api' extra.\n"
        "Install it with:\n"
        '    .venv\\Scripts\\python.exe -m pip install -e ".[api]"'
    ) from _exc
