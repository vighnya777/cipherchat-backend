"""Compatibility package for legacy import paths such as app.auth.oauth_service."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Expose the real project package under the legacy top-level name.
if "cipherchat" in sys.modules:
    cipherchat_module = sys.modules["cipherchat"]
    globals().update(cipherchat_module.__dict__)
    __path__ = [str(_ROOT / "cipherchat")]
else:
    import cipherchat as _cipherchat  # noqa: F401
    __path__ = [str(_ROOT / "cipherchat")]
    globals().update(sys.modules["cipherchat"].__dict__)

__all__ = ["create_app"]
