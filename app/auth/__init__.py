"""Compatibility namespace for app.auth.* imports."""

from __future__ import annotations

import sys

if "cipherchat.auth" not in sys.modules:
    import cipherchat.auth  # noqa: F401

for name in list(sys.modules):
    if name == "cipherchat.auth":
        sys.modules[__name__] = sys.modules[name]
        break

__all__ = []
