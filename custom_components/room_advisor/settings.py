"""Resolved per-room configuration, as the rules see it.

A rule receives settings that are already resolved: hub defaults merged with
that room's overrides, units normalised, and hysteresis bands expanded into
explicit boundaries. Nothing here reads configuration or Home Assistant.

Entity ids are deliberately absent: the observation layer turns them into
observations, which is all a rule is allowed to see.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING, Final

from .predicates import above_with_hysteresis, below_with_hysteresis

if TYPE_CHECKING:
    from collections.abc import Mapping

_NEGATIVE_BAND: Final = "a hysteresis band cannot be negative"
_NEGATIVE_DURATION: Final = "a duration cannot be negative"
_NEGATIVE_DELAY: Final = "an activation delay cannot be negative"
_MISORDERED: Final = (
    "a hysteresis band sits on the deactivation side: deactivate_at must be "
    "below activate_at when rising and above it when falling"
)


INDOOR_COMFORT_FLOOR: Final = "indoor_comfort_floor"
OUTDOOR_AIR_QUALITY_LIMIT: Final = "outdoor_air_quality_limit"

THRESHOLD_KEYS: Final = frozenset({INDOOR_COMFORT_FLOOR, OUTDOOR_AIR_QUALITY_LIMIT})
"""Every crossing point a room may carry.

Stated here rather than in the rules that read them, so that resolving a
room's configuration and reading it back are written against one vocabulary.
"""


class Direction(Enum):
    """Which way a value crosses a threshold to make advice worth giving."""

    RISING = auto()
    FALLING = auto()


@dataclass(frozen=True, slots=True)
class Threshold:
    """A crossing point with its two boundaries already worked out.

    A configured band is the total gap between activating and deactivating,
    and sits entirely on the deactivation side, so a threshold always means
    "the value at which advice starts". Build one with `rising` or `falling`
    rather than by hand: the direction decides which way the band goes, and
    getting it backwards yields advice that can never stop.
    """

    activate_at: float
    deactivate_at: float
    direction: Direction

    def __post_init__(self) -> None:
        """Reject boundaries that would leave advice unable to stop.

        Resolving configuration is where this is caught, once, rather than on
        every comparison for the life of the entry.
        """
        wrong_way = (
            self.deactivate_at > self.activate_at
            if self.direction is Direction.RISING
            else self.deactivate_at < self.activate_at
        )
        if wrong_way:
            raise ValueError(_MISORDERED)

    @classmethod
    def rising(cls, threshold: float, band: float = 0.0) -> Threshold:
        """Build a threshold that advice starts at by rising to it."""
        if band < 0:
            raise ValueError(_NEGATIVE_BAND)
        return cls(threshold, threshold - band, Direction.RISING)

    @classmethod
    def falling(cls, threshold: float, band: float = 0.0) -> Threshold:
        """Build a threshold that advice starts at by falling to it."""
        if band < 0:
            raise ValueError(_NEGATIVE_BAND)
        return cls(threshold, threshold + band, Direction.FALLING)

    @property
    def band(self) -> float:
        """The total gap between the two boundaries."""
        return abs(self.activate_at - self.deactivate_at)

    def is_met(self, value: float, *, active: bool) -> bool:
        """Whether this crossing point is met, holding state inside the band.

        `active` is whether the condition matched last evaluation, read from
        `ConditionState` and never from a rule's own published result.
        """
        compare = (
            above_with_hysteresis
            if self.direction is Direction.RISING
            else below_with_hysteresis
        )
        return compare(value, self.activate_at, self.deactivate_at, active=active)


@dataclass(frozen=True, slots=True)
class RoomSettings:
    """Everything one room's rules are allowed to know about its configuration.

    Immutable for the life of the config entry. Runtime state belongs to
    `ConditionState`, which changes every evaluation; the two are kept apart
    so that neither can be mistaken for the other.

    Every lookup raises `KeyError` for a name the room does not carry. A
    missing setting is a programming error, not a room that opted out — a room
    that opts out of a rule does so by not configuring its inputs, which the
    observation layer reports and the runner acts on.

    There is no room identifier here. A rule decides from readings and
    thresholds; giving it the room's name would let it answer differently in
    one room for reasons no test would cover.
    """

    thresholds: Mapping[str, Threshold]
    durations: Mapping[str, timedelta]
    activation_delays: Mapping[str, timedelta]

    def __post_init__(self) -> None:
        """Copy the mappings, and reject durations that run backwards.

        The copies are plain dicts rather than read-only views, matching the
        models: diagnostics dumps this, and a view cannot be serialised.
        """
        if any(duration < timedelta() for duration in self.durations.values()):
            raise ValueError(_NEGATIVE_DURATION)
        if any(delay < timedelta() for delay in self.activation_delays.values()):
            raise ValueError(_NEGATIVE_DELAY)
        object.__setattr__(self, "thresholds", dict(self.thresholds))
        object.__setattr__(self, "durations", dict(self.durations))
        object.__setattr__(self, "activation_delays", dict(self.activation_delays))

    def threshold(self, key: str) -> Threshold:
        """Return a resolved crossing point."""
        return self.thresholds[key]

    def duration(self, key: str) -> timedelta:
        """Return a resolved duration, such as how long a room must be empty."""
        return self.durations[key]

    def activation_delay(self, rule_id: str, default: timedelta) -> timedelta:
        """Return how long a rule must match before its advice is published.

        Falls back to the rule's own delay, so a room overrides only the
        delays it cares about.
        """
        return self.activation_delays.get(rule_id, default)
