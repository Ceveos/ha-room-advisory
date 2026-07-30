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
from .registry import RULES

if TYPE_CHECKING:
    from ..models import ConditionState, Observations
    from ..settings import RoomSettings
    from .base import Rule

AWAY: Final = "away"
RAIN_RISK: Final = "rain_risk"
WINDOW_CONTACTS: Final = "window_contacts"


def _close_advice(rule: Rule, obs: Observations, trigger: str) -> Advisory | None:
    """Advise closing a room's open windows, if `trigger` reads true.

    Shared by the rules that close a window because of something true of the
    whole house rather than of the room. They differ only in which input
    decides; the windows named and the advice given are the same.

    A window is named only while it is known open, so a contact that cannot be
    read neither triggers advice nor suppresses it. Another window being open
    is reason enough on its own.
    """
    windows = obs.group(WINDOW_CONTACTS)
    if not obs.value(trigger) or not windows.any_known_on:
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
        observations={trigger: obs.value(trigger)},
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
