"""Compatibility shim: app.auth.oauth_service -> cipherchat.auth.oauth_service."""

from __future__ import annotations

import sys

_real_module = "cipherchat.auth.oauth_service"
if _real_module not in sys.modules:
    import cipherchat.auth.oauth_service  # noqa: F401

sys.modules[__name__] = sys.modules[_real_module]
