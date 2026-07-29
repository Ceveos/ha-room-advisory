"""An `Observations` that remembers what a rule read.

Every rule is tested against this. A rule that reads an input it did not
declare would otherwise pass its own tests and then go quiet in a house that
happens not to have that sensor, because the runner never knew to wait for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from custom_components.room_advisor.models import Observations

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from custom_components.room_advisor.models import (
        GroupObservation,
        GuardState,
        Observation,
    )
    from custom_components.room_advisor.rules.base import Rule


class _RecordingGroups(Mapping[str, "GroupObservation"]):
    """A view over the group observations that records what is taken from it."""

    def __init__(
        self,
        groups: Mapping[str, GroupObservation],
        record: Callable[[str], None],
    ) -> None:
        """Wrap the groups, reporting each key read to `record`."""
        self._groups = groups
        self._record = record

    def __getitem__(self, key: str) -> GroupObservation:
        """Record and delegate."""
        self._record(key)
        return self._groups[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate the group keys, which is not a read of any of them."""
        return iter(self._groups)

    def __len__(self) -> int:
        """Return the number of groups."""
        return len(self._groups)

    def __contains__(self, key: object) -> bool:
        """Record and delegate, since asking is how a rule learns of a group."""
        if isinstance(key, str):
            self._record(key)
        return key in self._groups


class RecordingObservations(Observations):
    """Records every key reached for, however it was reached for."""

    def __init__(
        self,
        observations: Mapping[str, Observation] | None = None,
        groups: Mapping[str, GroupObservation] | None = None,
    ) -> None:
        """Snapshot the observations, and start with nothing read."""
        super().__init__(observations, groups)
        self.keys_read: set[str] = set()

    @property
    def groups(self) -> Mapping[str, GroupObservation]:
        """Return a view that records, since this mapping bypasses `group`."""
        return _RecordingGroups(super().groups, self.keys_read.add)

    def __getitem__(self, key: str) -> Observation:
        """Record and delegate."""
        self.keys_read.add(key)
        return super().__getitem__(key)

    def usable(self, *keys: str) -> bool:
        """Record and delegate."""
        self.keys_read.update(keys)
        return super().usable(*keys)

    def value(self, key: str) -> Any:  # noqa: ANN401 - matches Observations.value
        """Record and delegate."""
        self.keys_read.add(key)
        return super().value(key)

    def get_value(
        self,
        key: str,
        default: Any = None,  # noqa: ANN401 - matches Observations.get_value
    ) -> Any:  # noqa: ANN401 - matches Observations.get_value
        """Record and delegate."""
        self.keys_read.add(key)
        return super().get_value(key, default)

    def group(self, key: str) -> GroupObservation:
        """Record and delegate."""
        self.keys_read.add(key)
        return super().group(key)

    def guard_when(self, key: str, blocking: Callable[[Any], bool]) -> GuardState:
        """Record and delegate.

        `guard` routes through here, so both are covered by this one override.
        """
        self.keys_read.add(key)
        return super().guard_when(key, blocking)

    def undeclared_reads(self, rule: Rule) -> frozenset[str]:
        """Return the keys read that the rule never declared."""
        declared = {*rule.requires, *rule.optional, *rule.guards}
        return frozenset(self.keys_read - declared)
