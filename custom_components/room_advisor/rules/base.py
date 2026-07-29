"""What a rule is, how rules are registered, and how one is run.

A rule answers one question about one room and returns advice or nothing. It
declares the inputs it reads, and the runner refuses to call it until they are
readable, so no rule contains its own availability checks.

Nothing here imports Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Set
    from datetime import timedelta

    from ..models import Advisory, Category, ConditionState, Observations
    from ..settings import RoomSettings


class Rule(Protocol):
    """One condition worth advising on, and the inputs it needs to decide.

    Declared as read-only members: a rule states what it is, and nothing
    rewrites that at runtime.
    """

    @property
    def id(self) -> str:
        """Stable identifier, always `<category>.<reason_code>`."""

    @property
    def category(self) -> Category:
        """Which entity this rule's advice is published on."""

    @property
    def reason_code(self) -> str:
        """Stable public key the publisher renders wording from."""

    @property
    def requires(self) -> tuple[str, ...]:
        """Inputs that must be readable before `evaluate` is called."""

    @property
    def optional(self) -> tuple[str, ...]:
        """Inputs that may be missing.

        A rule that reads one owns the degraded answer, which must never be
        more aggressive than the full one.
        """

    @property
    def guards(self) -> tuple[str, ...]:
        """Vetoes, checked through `GuardState` rather than read."""

    @property
    def activation_delay(self) -> timedelta:
        """How long this condition must hold before its advice is published."""

    def evaluate(
        self,
        obs: Observations,
        settings: RoomSettings,
        state: ConditionState,
    ) -> Advisory | None:
        """Return advice if this condition holds, otherwise `None`.

        Deterministic and free of side effects: the same inputs must always
        give the same answer, because the runner may call it on any tick.
        """
        ...


class RuleDefinitionError(ValueError):
    """Raised when a rule cannot be registered as declared."""

    def __init__(self, rule_id: str, problem: str) -> None:
        """Record which rule is malformed and how."""
        super().__init__(f"rule {rule_id!r} {problem}")
        self.rule_id = rule_id


class RuleContractError(RuntimeError):
    """Raised when a rule returns an advisory that is not its own."""

    def __init__(self, rule_id: str, problem: str) -> None:
        """Record which rule broke its contract and how."""
        super().__init__(f"rule {rule_id!r} {problem}")
        self.rule_id = rule_id


class RuleRegistry:
    """The rules of every category, each category in precedence order.

    Registration order *is* the published precedence, so the order rules
    appear in their module is a product decision rather than a stylistic one.
    """

    def __init__(self) -> None:
        """Start with no rules registered."""
        self._by_category: dict[Category, list[Rule]] = {}
        self._by_id: dict[str, Rule] = {}

    def register[R: Rule](self, rule_class: type[R]) -> type[R]:
        """Register a rule class, next in its category's precedence order.

        Used as a decorator. The class is instantiated once, because a rule
        holds no per-room state and one instance serves every room.
        """
        rule = rule_class()
        self._validate(rule)
        self._by_id[rule.id] = rule
        self._by_category.setdefault(rule.category, []).append(rule)
        return rule_class

    def _validate(self, rule: Rule) -> None:
        """Reject a rule that cannot be run or cannot be told apart."""
        if rule.id in self._by_id:
            raise RuleDefinitionError(rule.id, "is already registered")
        if rule.id != f"{rule.category.value}.{rule.reason_code}":
            raise RuleDefinitionError(
                rule.id, "must be named '<category>.<reason_code>'"
            )
        declared = (*rule.requires, *rule.optional, *rule.guards)
        if len(declared) != len(set(declared)):
            raise RuleDefinitionError(rule.id, "declares an input as two kinds at once")
        if rule.activation_delay.total_seconds() < 0:
            raise RuleDefinitionError(rule.id, "has a negative activation delay")

    def __contains__(self, rule_id: str) -> bool:
        """Whether a rule of this id is registered."""
        return rule_id in self._by_id

    def __getitem__(self, rule_id: str) -> Rule:
        """Return a rule by id."""
        return self._by_id[rule_id]

    def for_category(self, category: Category) -> tuple[Rule, ...]:
        """Return a category's rules in precedence order, highest first."""
        return tuple(self._by_category.get(category, ()))

    def all_rules(self) -> tuple[Rule, ...]:
        """Return every rule, grouped by category in precedence order."""
        return tuple(rule for rules in self._by_category.values() for rule in rules)

    def declared_inputs(self) -> frozenset[str]:
        """Return every input key any registered rule may consult."""
        return frozenset(
            key
            for rule in self.all_rules()
            for key in (*rule.requires, *rule.optional, *rule.guards)
        )

    def guard_inputs(self) -> frozenset[str]:
        """Return the keys that must be present in every room's snapshot.

        Guards are not gated by the runner, because an unconfigured guard is
        meaningful, so a rule reaches for one unconditionally. The observation
        layer must therefore emit every guard key for every room, unconfigured
        ones included; a key it omits raises rather than being skipped.
        """
        return frozenset(key for rule in self.all_rules() for key in rule.guards)

    def undeclared_inputs(self, available: Set[str]) -> frozenset[str]:
        """Return the keys rules read that the observation layer cannot supply.

        An input a room lacks means "this rule does not apply here", which is
        right for a house with no CO₂ sensor and wrong for a mistyped key.
        Checking the two vocabularies against each other is what stops a typo
        from quietly disabling a rule in every house.
        """
        return self.declared_inputs() - available


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """What happened when one rule was offered a room.

    A rule that did not run is kept distinct from one that ran and found
    nothing: a room still waiting on a sensor is not a room with nothing worth
    doing, and the two are reported differently.
    """

    rule_id: str
    advisory: Advisory | None
    unreadable_inputs: tuple[str, ...] = ()

    @property
    def evaluated(self) -> bool:
        """Whether the rule was given the chance to decide."""
        return not self.unreadable_inputs

    @property
    def matched(self) -> bool:
        """Whether the rule produced advice."""
        return self.advisory is not None


def evaluate_rule(
    rule: Rule,
    obs: Observations,
    settings: RoomSettings,
    state: ConditionState,
) -> RuleOutcome:
    """Run one rule, unless one of its required inputs cannot be read.

    Exceptions from `evaluate` are not caught. A rule that raises is a bug,
    and reporting it as "no advice" would hide the bug behind a condition that
    may well hold.
    """
    unreadable = tuple(key for key in rule.requires if not obs.usable(key))
    if unreadable:
        return RuleOutcome(rule.id, None, unreadable)

    advisory = rule.evaluate(obs, settings, state)
    if advisory is not None:
        _check_advisory(rule, advisory)
    return RuleOutcome(rule.id, advisory)


def _check_advisory(rule: Rule, advisory: Advisory) -> None:
    """Reject advice attributed to something other than the rule that made it.

    Identity is `(room, rule_id)` and stabilisation timers hang off it, so a
    copied `rule_id` would silently adopt another rule's activation timer, and
    a copied `reason_code` would publish another rule's wording.
    """
    if advisory.rule_id != rule.id:
        raise RuleContractError(rule.id, f"returned advice for {advisory.rule_id!r}")
    if advisory.category is not rule.category:
        raise RuleContractError(rule.id, f"returned {advisory.category} advice")
    if advisory.reason_code != rule.reason_code:
        raise RuleContractError(
            rule.id, f"returned the reason {advisory.reason_code!r}"
        )


def evaluate_all(
    rules: Iterable[Rule],
    obs: Observations,
    settings: RoomSettings,
    state: ConditionState,
) -> tuple[RuleOutcome, ...]:
    """Run rules in order, returning an outcome for every one of them.

    Every rule is offered the room, including ones ranked below a match:
    stabilisation needs to know that a lower-ranked rule is still matching
    while a higher-ranked one waits out its delay.
    """
    return tuple(evaluate_rule(rule, obs, settings, state) for rule in rules)
