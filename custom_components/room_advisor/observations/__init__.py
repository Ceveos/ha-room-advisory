"""Turning a house's configured entities into one room's observations."""

from __future__ import annotations

from typing import Final

from .builder import BUILT_KEYS, build_observations
from .derived import DERIVED_KEYS, VacancyState, derive_observations, next_wake_up

OBSERVATION_KEYS: Final = BUILT_KEYS | DERIVED_KEYS
"""Every key a rule may name, once a snapshot has been derived."""

__all__ = [
    "BUILT_KEYS",
    "DERIVED_KEYS",
    "OBSERVATION_KEYS",
    "VacancyState",
    "build_observations",
    "derive_observations",
    "next_wake_up",
]
