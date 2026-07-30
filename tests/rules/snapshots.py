"""A room whose every input reads, for tests that vary one thing at a time.

Built by hand rather than from the observation layer: a rule test that went
through the builder would fail for reasons that have nothing to do with the
rule, and the two layers are joined by their vocabulary, which is asserted
here rather than assumed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any, Final

from custom_components.room_advisor.models import (
    GroupObservation,
    Observation,
    UnusableReason,
)
from custom_components.room_advisor.settings import RoomSettings, Threshold
from tests.rules.recording import RecordingObservations

READINGS: Final[dict[str, Any]] = {
    "away": False,
    "rain_risk": False,
    "outdoor_temperature": 18.0,
    "outdoor_humidity": 50.0,
    "outdoor_air_quality": 20.0,
    "outdoor_dew_point": 7.4,
    "temperature_advantage": 4.0,
    "indoor_temperature": 22.0,
    "indoor_co2": 600.0,
    "occupancy": True,
    "unoccupied_for": 0.0,
    "hvac_conditioning": False,
    "fan": False,
}
"""A plausible usable value for every single-entity observation key."""

GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "window_contacts": ("binary_sensor.window_a", "binary_sensor.window_b"),
    "lights": ("light.ceiling", "light.lamp"),
}
"""The members of every multi-entity observation key."""

SOURCES: Final[dict[str, str]] = {
    "away": "alarm_control_panel.home",
    "rain_risk": "binary_sensor.rain_expected",
}
"""The entity a reading came from, where a rule reports one."""


def group(
    key: str,
    *,
    known_on: tuple[str, ...] = (),
    unusable: tuple[str, ...] = (),
) -> GroupObservation:
    """Build a group whose remaining members read off."""
    members = GROUPS[key]
    return GroupObservation(
        key=key,
        configured=members,
        known_on=known_on,
        known_off=tuple(m for m in members if m not in {*known_on, *unusable}),
        unusable=unusable,
    )


def snapshot(
    readings: dict[str, Any] | None = None,
    groups: dict[str, GroupObservation] | None = None,
) -> RecordingObservations:
    """Build a room in which every input reads, then apply the overrides.

    A value of `None` marks an input unusable, which is how a test says "this
    room's sensor is dead" without restating the twelve that are fine.
    """
    values = READINGS | (readings or {})
    return RecordingObservations(
        {
            key: (
                Observation.missing(
                    key,
                    UnusableReason.UNAVAILABLE,
                    source_entity_id=SOURCES.get(key),
                )
                if value is None
                else Observation.reading(key, value, source_entity_id=SOURCES.get(key))
            )
            for key, value in values.items()
        },
        {key: group(key) for key in GROUPS} | (groups or {}),
    )


def without_source(obs: RecordingObservations, key: str) -> RecordingObservations:
    """Return the same room with one reading attributed to no single entity."""
    return RecordingObservations(
        dict(obs) | {key: replace(obs[key], source_entity_id=None)},
        dict(obs.groups),
    )


class AnySettings(RoomSettings):
    """A room configured for whatever setting a rule asks for.

    `RoomSettings` raises for a name the room does not carry, which is right
    in a running house and wrong for tests that run every rule against one
    room: the first rule to reach for a threshold would raise, and the reads
    it was about to make would go unrecorded.
    """

    def threshold(self, key: str) -> Threshold:
        """Return the room's threshold, or one crossed by a high reading."""
        return self.thresholds.get(key, Threshold.rising(0.0))

    def duration(self, key: str) -> timedelta:
        """Return the room's duration, or one any elapsed time has served."""
        return self.durations.get(key, timedelta(0))


ANY_SETTINGS: Final = AnySettings(thresholds={}, durations={}, activation_delays={})

EXTREMES: Final = (None, 5000.0, -5000.0)
"""Numeric levels: as configured, then either side of any crossing point."""


def every_room(*, dead_member: bool = False) -> list[RecordingObservations]:
    """Every room a rule must read the same way.

    Both settings of each boolean, both a shut room and one with something
    open, and numeric readings driven past any threshold in both directions.
    These are not plausible rooms; they are the rooms that force a rule down
    each of its branches, so that a read it makes only when a reading is
    extreme is a read these tests have seen.

    With `dead_member`, one member of every group cannot be read while the
    group as a whole still can, which is the state that separates advice to
    shut something from advice to open it.
    """
    rooms = []
    for inverted in (False, True):
        for opened in (False, True):
            for level in EXTREMES:
                rooms.append(
                    snapshot(
                        {
                            key: (not value if inverted else value)
                            if isinstance(value, bool)
                            else (value if level is None else level)
                            for key, value in READINGS.items()
                        },
                        {
                            key: _shaped(key, opened=opened, dead_member=dead_member)
                            for key in GROUPS
                        },
                    )
                )
    return rooms


def _shaped(key: str, *, opened: bool, dead_member: bool) -> GroupObservation:
    """Build one group, optionally with its first member unreadable."""
    members = GROUPS[key]
    unusable = members[:1] if dead_member else ()
    readable = members[1:] if dead_member else members
    return group(key, known_on=readable[:1] if opened else (), unusable=unusable)
