"""Compatibility shim: app.auth.validators -> cipherchat.auth.validators."""

from __future__ import annotations

import sys

_real_module = "cipherchat.auth.validators"
if _real_module not in sys.modules:
    import cipherchat.auth.validators  # noqa: F401

sys.modules[__name__] = sys.modules[_real_module]
