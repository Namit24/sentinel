"""Compatibility bridge for launching the package while inside the package directory.

When the current working directory is `sentinelops/`, imports like
`uvicorn sentinelops.main:app` fail because Python cannot see the repo root package.
This proxy package extends the package search path back to the real package directory.
"""

from __future__ import annotations

from pathlib import Path

_BRIDGE_DIR = Path(__file__).resolve().parent
_REAL_PACKAGE_DIR = _BRIDGE_DIR.parent

__path__ = [str(_BRIDGE_DIR), str(_REAL_PACKAGE_DIR)]
