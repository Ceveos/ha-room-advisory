"""The one registry every rule registers into.

Kept apart from the rule modules so that importing a category does not import
the registry through the package, which would import the category again.
"""

from __future__ import annotations

from typing import Final

from .base import RuleRegistry

RULES: Final = RuleRegistry()
"""Every rule the integration ships, each category in precedence order."""
