"""Comparison helpers shared by the rules.

Each helper holds one policy in a single place so that every rule applies it
identically. Like `models`, this module imports nothing from Home Assistant.
"""

from __future__ import annotations

from typing import Final

from .models import GuardState

_PERMITTING_STATES: Final = frozenset({GuardState.NOT_CONFIGURED, GuardState.SATISFIED})

_ABOVE_MISORDERED: Final = (
    "above_with_hysteresis requires deactivate_at <= activate_at, "
    "otherwise the condition can never deactivate"
)
_BELOW_MISORDERED: Final = (
    "below_with_hysteresis requires deactivate_at >= activate_at, "
    "otherwise the condition can never deactivate"
)


def guards_permit_opening(*states: GuardState) -> bool:
    """Whether every guard allows advising something to be opened.

    A guard permits opening only when it is unconfigured or satisfied. An
    unconfigured guard is skipped because its absence is the user's explicit
    choice; a configured guard that cannot be read is not, so `UNUSABLE`
    withholds the advice exactly as `BLOCKING` does. Advising a window open
    into rain the integration could not see is the failure this prevents.

    With no guards the result is true, which is what a rule that declares none
    means.
    """
    return all(state in _PERMITTING_STATES for state in states)


def above_with_hysteresis(
    value: float,
    activate_at: float,
    deactivate_at: float,
    *,
    active: bool,
) -> bool:
    """Whether a value that becomes true by rising is true now.

    Rises to `activate_at` to become true, and falls below `deactivate_at` to
    become false again. `active` is whether the condition currently holds, read
    from the stabilisation state and never from a rule's own last result.

    A band of zero collapses both boundaries onto the threshold, leaving a
    plain comparison.
    """
    if deactivate_at > activate_at:
        raise ValueError(_ABOVE_MISORDERED)
    return value >= (deactivate_at if active else activate_at)


def below_with_hysteresis(
    value: float,
    activate_at: float,
    deactivate_at: float,
    *,
    active: bool,
) -> bool:
    """Whether a value that becomes true by falling is true now.

    Falls to `activate_at` to become true, and rises above `deactivate_at` to
    become false again. The mirror of `above_with_hysteresis`, for the rules
    that compare in the other direction.
    """
    if deactivate_at < activate_at:
        raise ValueError(_BELOW_MISORDERED)
    return value <= (deactivate_at if active else activate_at)
