"""The rules: one module per category, plus the machinery they share.

Importing this package registers every rule. Rule modules are imported for
that effect, so a category left out here is a category that silently gives no
advice.
"""

from __future__ import annotations

from . import window
from .registry import RULES

__all__ = ["RULES", "window"]
