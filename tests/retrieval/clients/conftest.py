"""Conftest for retrieval/clients tests — stubs fastembed before any import."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Inject a fake fastembed module so QueryEmbedder can be imported without the
# real package being installed. Must happen before src.retrieval.* imports.
# ---------------------------------------------------------------------------
if "fastembed" not in sys.modules:
    _fake_fastembed = types.ModuleType("fastembed")
    _fake_fastembed.TextEmbedding = MagicMock  # type: ignore[attr-defined]
    sys.modules["fastembed"] = _fake_fastembed
