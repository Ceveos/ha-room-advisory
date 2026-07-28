"""Core data structures shared by every layer of Room Advisor.

This module imports nothing from Home Assistant. The rule and observation
suites are built on it and run without a `hass` instance.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum, auto
from types import MappingProxyType
from typing import Any, Final

type AdvisoryIdentity = tuple[str, str]
"""A room subentry id paired with a rule id, and nothing else."""


class Action(StrEnum):
    """A published advice state.

    The values are the entity states consumers match on, so they are part of
    the public contract.
    """

    OPEN = "open"
    CLOSE = "close"
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    NONE = "none"


class Category(StrEnum):
    """A family of advice, published as one entity per room.

    A closed set: a category is evaluated by rules, so adding one means adding
    rules rather than configuration. Consumers of a category should iterate
    this enum rather than branch on its members.
    """

    WINDOW = "window"
    FAN = "fan"
    LIGHT = "light"

    @property
    def advisable_actions(self) -> frozenset[Action]:
        """The actions an advisory in this category may carry.

        These are also the options the category's entity declares, minus
        `NONE`, which is the absence of advice rather than advice.
        """
        return _ADVISABLE_ACTIONS[self]


# Advice is corrective: it names something worth putting right. Lighting
# therefore advises only turning off, because a light being off is not a fault
# and no reading distinguishes a dark room from one someone wants dark.
_ADVISABLE_ACTIONS: Final[Mapping[Category, frozenset[Action]]] = {
    Category.WINDOW: frozenset({Action.OPEN, Action.CLOSE}),
    Category.FAN: frozenset({Action.TURN_ON, Action.TURN_OFF}),
    Category.LIGHT: frozenset({Action.TURN_OFF}),
}


class UnusableReason(StrEnum):
    """Why an observation cannot be read.

    `NOT_CONFIGURED` is deliberately distinct from the rest: an unconfigured
    guard is skipped, while a configured-but-broken one withholds opening
    advice.
    """

    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    UNCONVERTIBLE = "unconvertible"
    NOT_YET_SEEN = "not_yet_seen"
    SOURCE_OFFLINE = "source_offline"


class GuardState(Enum):
    """The four-state result of checking a guard.

    Internal to evaluation and never published, so the values carry no
    meaning.
    """

    NOT_CONFIGURED = auto()
    SATISFIED = auto()
    BLOCKING = auto()
    UNUSABLE = auto()


class InvalidAdvisoryError(ValueError):
    """Raised when an advisory carries an action its category cannot publish."""

    def __init__(self, category: Category, action: Action) -> None:
        """Record the category and the action it cannot advise."""
        super().__init__(f"{category} cannot advise {action}")
        self.category = category
        self.action = action


class UnusableObservationError(LookupError):
    """Raised when an observation that cannot be read is read anyway.

    A rule that reads a key outside its declared inputs fails here rather than
    silently seeing `None`.
    """

    def __init__(self, key: str, reason: UnusableReason | None) -> None:
        """Record the key and the reason it could not be read."""
        super().__init__(f"observation {key!r} is unusable: {reason}")
        self.key = key
        self.reason = reason


def _copied(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy a mapping so the caller's later edits cannot reach it.

    A plain `dict` rather than a read-only view, so these structures stay
    serialisable and copyable. The `Mapping` annotation is what keeps callers
    from writing to them.
    """
    return dict(mapping)


@dataclass(frozen=True, slots=True)
class Observation:
    """One input of one room at one moment."""

    key: str
    value: Any
    unit: str | None
    unusable_reason: UnusableReason | None
    source_entity_id: str | None

    def __post_init__(self) -> None:
        """Reject an observation whose value and reason disagree.

        A usable observation without a value would be read as a real reading:
        a guard would see `None`, find it falsy, and report `SATISFIED`.
        """
        if self.unusable_reason is None and self.value is None:
            raise ValueError(_USABLE_WITHOUT_VALUE)
        if self.unusable_reason is not None and self.value is not None:
            raise ValueError(_UNUSABLE_WITH_VALUE)

    @property
    def usable(self) -> bool:
        """Whether the value may be read."""
        return self.unusable_reason is None

    @classmethod
    def reading(
        cls,
        key: str,
        value: Any,  # noqa: ANN401 - observations carry floats, bools and strings
        *,
        unit: str | None = None,
        source_entity_id: str | None = None,
    ) -> Observation:
        """Build a usable observation."""
        return cls(
            key=key,
            value=value,
            unit=unit,
            unusable_reason=None,
            source_entity_id=source_entity_id,
        )

    @classmethod
    def missing(
        cls,
        key: str,
        reason: UnusableReason,
        *,
        unit: str | None = None,
        source_entity_id: str | None = None,
    ) -> Observation:
        """Build an unusable observation."""
        return cls(
            key=key,
            value=None,
            unit=unit,
            unusable_reason=reason,
            source_entity_id=source_entity_id,
        )


_UNUSABLE_WITH_VALUE: Final = "an unusable observation must not carry a value"
_USABLE_WITHOUT_VALUE: Final = "a usable observation must carry a value"
_GROUP_NOT_PARTITIONED: Final = (
    "known_on, known_off and unusable must partition configured"
)
_ACTIVE_SINCE_MISMATCH: Final = "active_since must hold exactly the matching rules"


@dataclass(frozen=True, slots=True)
class GroupObservation:
    """A multi-entity input, such as a room's window contacts.

    Membership is kept rather than reduced to a boolean, so a rule can tell
    which members it could read.
    """

    key: str
    configured: tuple[str, ...]
    known_on: tuple[str, ...]
    known_off: tuple[str, ...]
    unusable: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject a group whose members do not partition its configuration."""
        members = (*self.known_on, *self.known_off, *self.unusable)
        if len(members) != len(set(members)) or set(members) != set(self.configured):
            raise ValueError(_GROUP_NOT_PARTITIONED)

    @property
    def usable(self) -> bool:
        """Whether at least one member can be read.

        Gates whether a rule runs at all. Opening rules additionally require
        `all_usable_and_off`. False both for a group with no members and for
        one whose members are all unreadable; `configured` tells them apart.
        """
        return bool(self.configured) and len(self.unusable) < len(self.configured)

    @property
    def any_known_on(self) -> bool:
        """Whether at least one member is known to be open or lit."""
        return bool(self.known_on)

    @property
    def all_usable_and_off(self) -> bool:
        """Whether every member is readable and closed or dark.

        False whenever any member is unusable. This is what every opening rule
        consults, so advice to open is never given on partial information.
        """
        return bool(self.configured) and not self.unusable and not self.known_on


class Observations(Mapping[str, Observation]):
    """Every input of one room at one moment.

    Rules reach their inputs only through this interface. Indexing yields the
    `Observation` itself, including unusable ones, so diagnostics can explain
    a room; `value` yields the reading and refuses when it is not usable.
    """

    def __init__(
        self,
        observations: Mapping[str, Observation] | None = None,
        groups: Mapping[str, GroupObservation] | None = None,
    ) -> None:
        """Snapshot the observations and groups of one evaluation."""
        self._observations: Final = dict(observations or {})
        self._groups: Final = dict(groups or {})

    def __getitem__(self, key: str) -> Observation:
        """Return an observation whether or not it is usable."""
        return self._observations[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate the observation keys, excluding groups."""
        return iter(self._observations)

    def __len__(self) -> int:
        """Return the number of observations, excluding groups."""
        return len(self._observations)

    @property
    def groups(self) -> Mapping[str, GroupObservation]:
        """The multi-entity inputs, which are not part of the mapping."""
        return MappingProxyType(self._groups)

    def usable(self, *keys: str) -> bool:
        """Whether every named key can be read.

        Accepts group keys, for which usability is the group's own test. A key
        the room never built is not usable, so a rule can be gated on an input
        this room has no sensor for.
        """
        return all(self._is_usable(key) for key in keys)

    def _is_usable(self, key: str) -> bool:
        """Prefer an observation over a group of the same name."""
        observation = self._observations.get(key)
        if observation is not None:
            return observation.usable
        group = self._groups.get(key)
        if group is not None:
            return group.usable
        return False

    def value(self, key: str) -> Any:  # noqa: ANN401 - see Observation.value
        """Return a usable reading.

        Raises `KeyError` if the room has no such observation, and
        `UnusableObservationError` if it has one that cannot be read.
        """
        observation = self._observations[key]
        if not observation.usable:
            raise UnusableObservationError(key, observation.unusable_reason)
        return observation.value

    def get_value(
        self,
        key: str,
        default: Any = None,  # noqa: ANN401 - see Observation.value
    ) -> Any:  # noqa: ANN401 - see Observation.value
        """Return a usable reading, or `default` if there is not one.

        Named apart from `Mapping.get`, which keeps its usual meaning of
        returning the `Observation`.
        """
        observation = self._observations.get(key)
        if observation is None or not observation.usable:
            return default
        return observation.value

    def group(self, key: str) -> GroupObservation:
        """Return a multi-entity input, raising `KeyError` if there is none."""
        return self._groups[key]

    def guard(self, key: str) -> GuardState:
        """Check a guard that blocks while its input is true."""
        return self.guard_when(key, bool)

    def guard_when(self, key: str, blocking: Callable[[Any], bool]) -> GuardState:
        """Check a guard, `blocking` deciding what its reading means.

        Every guard key a rule may consult is present in the snapshot, an
        unconfigured one carrying `NOT_CONFIGURED`. An unknown key is a
        programming error and raises `KeyError`, because reading it as an
        unconfigured guard would skip the guard instead.
        """
        observation = self._observations[key]
        if observation.unusable_reason is UnusableReason.NOT_CONFIGURED:
            return GuardState.NOT_CONFIGURED
        if not observation.usable:
            return GuardState.UNUSABLE
        return (
            GuardState.BLOCKING if blocking(observation.value) else GuardState.SATISFIED
        )


@dataclass(frozen=True, slots=True)
class Advisory:
    """One thing worth doing in one room, and why.

    A fresh instance is produced on every evaluation. Identity is
    `(room_subentry_id, rule_id)` and nothing else, so a temperature ticking
    by a tenth of a degree does not restart an activation timer.
    """

    rule_id: str
    category: Category
    action: Action
    reason_code: str
    reason_placeholders: Mapping[str, Any] = field(default_factory=dict)
    related_entities: tuple[str, ...] = ()
    source_entities: Mapping[str, str] = field(default_factory=dict)
    observations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject an action its category cannot advise, and seal the mappings."""
        if self.action not in self.category.advisable_actions:
            raise InvalidAdvisoryError(self.category, self.action)
        object.__setattr__(
            self, "reason_placeholders", _copied(self.reason_placeholders)
        )
        object.__setattr__(self, "source_entities", _copied(self.source_entities))
        object.__setattr__(self, "observations", _copied(self.observations))

    def identity_in(self, room_subentry_id: str) -> AdvisoryIdentity:
        """Return this advisory's identity within a room."""
        return (room_subentry_id, self.rule_id)


@dataclass(frozen=True, slots=True)
class ConditionState:
    """Which conditions matched last evaluation, and since when.

    A condition latches on matching, not on publication: an advisory displaced
    by a higher-ranked one is still matching, and must not fall back to its
    activation threshold. This is per condition, and separate from the
    published advisory's `active_since`.
    """

    matching: frozenset[str]
    active_since: Mapping[str, datetime]

    def __post_init__(self) -> None:
        """Reject timings that do not correspond to the matching conditions."""
        if set(self.active_since) != set(self.matching):
            raise ValueError(_ACTIVE_SINCE_MISMATCH)
        object.__setattr__(self, "active_since", _copied(self.active_since))

    def is_active(self, rule_id: str) -> bool:
        """Whether this condition matched the last evaluation."""
        return rule_id in self.matching
