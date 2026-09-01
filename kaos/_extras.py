"""Helpers for optional-dependency ("extras") boundaries (v2.0).

The base install (``pip install kaos-harness``) ships the flight recorder and
the brain only. Heavier surfaces sit behind extras, and every import of an
extra's third-party package must go through :func:`require` so its absence
produces one actionable line instead of a bare traceback.
"""

from __future__ import annotations

import importlib


class MissingExtraError(ImportError):
    """An optional dependency is not installed. ``str()`` is user-facing."""


def require(module: str, extra: str, feature: str):
    """Import ``module`` or raise MissingExtraError naming the extra.

    >>> httpx = require("httpx", "router", "model providers")
    """
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise MissingExtraError(
            f"{feature} requires the '{module}' package, which is part of "
            f"the '{extra}' extra. Install it with:\n\n"
            f"    pip install 'kaos-harness[{extra}]'\n\n"
            f"(or 'kaos-harness[all]' for everything)"
        ) from e
