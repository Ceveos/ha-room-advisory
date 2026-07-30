"""Advice about a room's windows.

Rules are registered in the order they are published in: the highest-ranked
rule that matches and has served its delay is the advice a room shows. Moving
a class in this file changes what users are told, so the order is a product
decision.

Every rule here advises closing, and each requires a window already known to
be open. Advice to open is the opposite case and carries the opposite
asymmetry, so it is kept separate.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from ..models import Action, Advisory, Category
from ..settings import INDOOR_COMFORT_FLOOR, OUTDOOR_AIR_QUALITY_LIMIT
from .registry import RULES

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from ..models import ConditionState, Observations
    from ..settings import RoomSettings
    from .base import Rule

AWAY: Final = "away"
RAIN_RISK: Final = "rain_risk"
HVAC_CONDITIONING: Final = "hvac_conditioning"
INDOOR_TEMPERATURE: Final = "indoor_temperature"
OUTDOOR_AIR_QUALITY: Final = "outdoor_air_quality"
WINDOW_CONTACTS: Final = "window_contacts"


def _close_advice(
    rule: Rule,
    obs: Observations,
    trigger: str,
    holds: Callable[[Any], bool] = bool,
) -> Advisory | None:
    """Advise closing a room's open windows, if `trigger` reads as a problem.

    Shared by every rule that closes a window. They differ only in which input
    decides and what counts as a problem; the windows named and the advice
    given are the same.

    A window is named only while it is known open, so a contact that cannot be
    read neither triggers advice nor suppresses it. Another window being open
    is reason enough on its own.
    """
    windows = obs.group(WINDOW_CONTACTS)
    reading = obs.value(trigger)
    if not holds(reading) or not windows.any_known_on:
        return None

    source = obs[trigger].source_entity_id
    return Advisory(
        rule_id=rule.id,
        category=rule.category,
        action=Action.CLOSE,
        reason_code=rule.reason_code,
        reason_placeholders={"window_count": len(windows.known_on)},
        related_entities=windows.known_on,
        source_entities={} if source is None else {trigger: source},
        observations={trigger: reading},
    )


@RULES.register
class AwaySecure:
    """A window is open and nobody is home.

    Ranked first because it is the only window rule about security rather
    than comfort, and it is immediate for the same reason: advice to shut an
    unattended house delivered two minutes late is advice delivered after the
    car has left.
    """

    id = "window.away_secure"
    category = Category.WINDOW
    reason_code = "away_secure"
    requires = (AWAY, WINDOW_CONTACTS)
    optional: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    activation_delay = timedelta(0)

    def evaluate(
        self,
        obs: Observations,
        _settings: RoomSettings,
        _state: ConditionState,
    ) -> Advisory | None:
        """Advise closing while the house is away and a window is open."""
        return _close_advice(self, obs, AWAY)


@RULES.register
class RainIncoming:
    """A window is open and meaningful rain is expected.

    Immediate: the cost of being late is water indoors, and the cost of being
    early is a window closed shortly before rain that arrives anyway.
    """

    id = "window.rain_incoming"
    category = Category.WINDOW
    reason_code = "rain_incoming"
    requires = (RAIN_RISK, WINDOW_CONTACTS)
    optional: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    activation_delay = timedelta(0)

    def evaluate(
        self,
        obs: Observations,
        _settings: RoomSettings,
        _state: ConditionState,
    ) -> Advisory | None:
        """Advise closing while rain is expected and a window is open."""
        return _close_advice(self, obs, RAIN_RISK)


@RULES.register
class OutdoorAirQuality:
    """A window is open onto air worse than the room's own.

    Ranked below the safety rules and above the comfort ones: bad outdoor air
    is a health matter, but a brief spike is not worth advising on, which is
    what the delay is for.
    """

    id = "window.outdoor_air_quality"
    category = Category.WINDOW
    reason_code = "outdoor_air_quality"
    requires = (OUTDOOR_AIR_QUALITY, WINDOW_CONTACTS)
    optional: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    activation_delay = timedelta(seconds=30)

    def evaluate(
        self,
        obs: Observations,
        settings: RoomSettings,
        state: ConditionState,
    ) -> Advisory | None:
        """Advise closing while outdoor air is above the room's limit."""
        limit = settings.threshold(OUTDOOR_AIR_QUALITY_LIMIT)
        active = state.is_active(self.id)
        return _close_advice(
            self,
            obs,
            OUTDOOR_AIR_QUALITY,
            lambda reading: limit.is_met(reading, active=active),
        )


@RULES.register
class RoomTooCold:
    """A window is open and the room has fallen below its comfort floor.

    The longest delay of the closing rules: a room cools slowly, and a
    thermometer briefly reading low in a draught is not a reason to be told
    anything.
    """

    id = "window.room_too_cold"
    category = Category.WINDOW
    reason_code = "room_too_cold"
    requires = (INDOOR_TEMPERATURE, WINDOW_CONTACTS)
    optional: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    activation_delay = timedelta(minutes=2)

    def evaluate(
        self,
        obs: Observations,
        settings: RoomSettings,
        state: ConditionState,
    ) -> Advisory | None:
        """Advise closing while the room is below its comfort floor."""
        floor = settings.threshold(INDOOR_COMFORT_FLOOR)
        active = state.is_active(self.id)
        return _close_advice(
            self,
            obs,
            INDOOR_TEMPERATURE,
            lambda reading: floor.is_met(reading, active=active),
        )


@RULES.register
class HvacConflict:
    """A window is open while the heating or cooling is running.

    Ranked last of the closing rules because it is the one whose cost is only
    money, and delayed the least of the comfort rules because that cost is
    accruing the whole time.
    """

    id = "window.hvac_conflict"
    category = Category.WINDOW
    reason_code = "hvac_conflict"
    requires = (HVAC_CONDITIONING, WINDOW_CONTACTS)
    optional: tuple[str, ...] = ()
    guards: tuple[str, ...] = ()
    activation_delay = timedelta(seconds=60)

    def evaluate(
        self,
        obs: Observations,
        _settings: RoomSettings,
        _state: ConditionState,
    ) -> Advisory | None:
        """Advise closing while the room is being conditioned."""
        return _close_advice(self, obs, HVAC_CONDITIONING)
