"""The entities Room Advisor reads, and how they are offered in the config flow.

This module is the single source of truth for the input vocabulary: the keys
that are stored, the entities each key will accept, which keys hold several
entities, and whether a key belongs to the house or to one room. The
observation layer builds its snapshot from these same keys, so a key added here
is the one place it is named.

House and room inputs share one vocabulary and one stored shape. They differ
only in where they are written and in what offers them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Any, Final

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
)

CONF_INPUTS: Final = "inputs"
"""Where entities are stored: a room's subentry data, the hub's options.

Absent, or absent for a given key, means the input is not configured. That is
an ordinary state, not an error: every input is optional and missing ones
disable only the rules that require them.
"""


class InputScope(Enum):
    """Who an input belongs to.

    A shared input is configured once for the house. A room input is
    configured per room.
    """

    SHARED = auto()
    ROOM = auto()


class InputKey(StrEnum):
    """An entity Room Advisor reads.

    The values are stored in configuration, so renaming one is a migration.
    """

    OUTDOOR_TEMPERATURE = "outdoor_temperature"
    OUTDOOR_HUMIDITY = "outdoor_humidity"
    OUTDOOR_AIR_QUALITY = "outdoor_air_quality"
    RAIN_RISK = "rain_risk"
    AWAY = "away"
    INDOOR_TEMPERATURE = "indoor_temperature"
    INDOOR_CO2 = "indoor_co2"
    OCCUPANCY = "occupancy"
    WINDOW_CONTACTS = "window_contacts"
    LIGHTS = "lights"
    FAN = "fan"
    HVAC = "hvac"


@dataclass(frozen=True, slots=True)
class InputSpec:
    """What an input accepts, what it proposes, and how many it holds.

    Accepting and proposing are different questions. The picker accepts every
    entity the observation layer can read, because a contact sensor with no
    device class is still a contact sensor. The area scan proposes only
    entities whose device class says what they are, because a proposal the user
    has to undo is worse than no proposal.
    """

    key: InputKey
    scope: InputScope
    accepts: tuple[EntityFilterSelectorConfig, ...]
    suggests: tuple[EntityFilterSelectorConfig, ...] | None = None
    multiple: bool = False

    @property
    def suggested(self) -> tuple[EntityFilterSelectorConfig, ...]:
        """Return the filters the area scan proposes from."""
        return self.accepts if self.suggests is None else self.suggests

    def selector(self) -> EntitySelector:
        """Build the picker this input is offered through."""
        return EntitySelector(
            EntitySelectorConfig(filter=list(self.accepts), multiple=self.multiple)
        )

    def matches(self, domain: str, device_class: str | None) -> bool:
        """Return whether an entity is worth proposing for this input.

        Matches on domain and device class, which is what every filter here
        narrows on. A filter that narrowed further would need this to narrow
        with it.
        """
        return any(
            domain in _as_list(entity_filter["domain"])
            and (
                "device_class" not in entity_filter
                or device_class in _as_list(entity_filter["device_class"])
            )
            for entity_filter in self.suggested
        )


def _as_list(value: str | list[str]) -> list[str]:
    """Normalise a selector filter field, which may be a string or a list."""
    return [value] if isinstance(value, str) else value


INPUTS: Final[tuple[InputSpec, ...]] = (
    InputSpec(
        key=InputKey.OUTDOOR_TEMPERATURE,
        scope=InputScope.SHARED,
        accepts=(
            EntityFilterSelectorConfig(domain="sensor", device_class="temperature"),
            EntityFilterSelectorConfig(domain="weather"),
        ),
    ),
    InputSpec(
        key=InputKey.OUTDOOR_HUMIDITY,
        scope=InputScope.SHARED,
        accepts=(
            EntityFilterSelectorConfig(domain="sensor", device_class="humidity"),
            EntityFilterSelectorConfig(domain="weather"),
        ),
    ),
    InputSpec(
        key=InputKey.OUTDOOR_AIR_QUALITY,
        scope=InputScope.SHARED,
        accepts=(EntityFilterSelectorConfig(domain="sensor"),),
    ),
    InputSpec(
        key=InputKey.RAIN_RISK,
        scope=InputScope.SHARED,
        accepts=(
            EntityFilterSelectorConfig(
                domain=["binary_sensor", "input_boolean", "switch"]
            ),
        ),
    ),
    InputSpec(
        key=InputKey.AWAY,
        scope=InputScope.SHARED,
        accepts=(
            EntityFilterSelectorConfig(
                domain=[
                    "alarm_control_panel",
                    "binary_sensor",
                    "device_tracker",
                    "input_boolean",
                    "person",
                ]
            ),
        ),
        multiple=True,
    ),
    InputSpec(
        key=InputKey.INDOOR_TEMPERATURE,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(domain="sensor", device_class="temperature"),
        ),
    ),
    InputSpec(
        key=InputKey.INDOOR_CO2,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(domain="sensor", device_class="carbon_dioxide"),
        ),
    ),
    InputSpec(
        key=InputKey.OCCUPANCY,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(
                domain=["binary_sensor", "input_boolean", "person"]
            ),
        ),
        suggests=(
            EntityFilterSelectorConfig(
                domain="binary_sensor",
                device_class=["occupancy", "motion", "presence"],
            ),
        ),
    ),
    InputSpec(
        key=InputKey.WINDOW_CONTACTS,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(
                domain=["binary_sensor", "input_boolean", "switch"]
            ),
        ),
        suggests=(
            EntityFilterSelectorConfig(
                domain="binary_sensor",
                device_class=["window", "door", "opening"],
            ),
        ),
        multiple=True,
    ),
    InputSpec(
        key=InputKey.LIGHTS,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(domain=["light", "switch", "input_boolean"]),
        ),
        suggests=(EntityFilterSelectorConfig(domain="light"),),
        multiple=True,
    ),
    InputSpec(
        key=InputKey.FAN,
        scope=InputScope.ROOM,
        accepts=(
            EntityFilterSelectorConfig(domain=["fan", "switch", "input_boolean"]),
        ),
        suggests=(EntityFilterSelectorConfig(domain="fan"),),
    ),
    InputSpec(
        key=InputKey.HVAC,
        scope=InputScope.ROOM,
        accepts=(EntityFilterSelectorConfig(domain="climate"),),
    ),
)
"""Every input, in the order its form offers it."""

SHARED_INPUTS: Final = tuple(spec for spec in INPUTS if spec.scope is InputScope.SHARED)
"""The house inputs, configured once on the hub."""

ROOM_INPUTS: Final = tuple(spec for spec in INPUTS if spec.scope is InputScope.ROOM)
"""The inputs configured per room."""


def inputs_schema(specs: Sequence[InputSpec]) -> vol.Schema:
    """Build the form a set of entities is chosen on.

    Every field is optional, because every input is.
    """
    return vol.Schema({vol.Optional(spec.key.value): spec.selector() for spec in specs})


def clean_inputs(
    user_input: Mapping[str, Any], specs: Sequence[InputSpec]
) -> dict[str, str | list[str]]:
    """Reduce a submitted form to what is worth storing.

    Cleared fields are dropped rather than stored empty, so "not configured"
    has one representation. Duplicates in a multi-entity input are removed,
    keeping the order the user chose.
    """
    cleaned: dict[str, str | list[str]] = {}
    for spec in specs:
        value = user_input.get(spec.key.value)
        if spec.multiple:
            entity_ids = _unique(value if isinstance(value, list) else [])
            if entity_ids:
                cleaned[spec.key.value] = entity_ids
        elif isinstance(value, str) and value:
            cleaned[spec.key.value] = value
    return cleaned


def _unique(entity_ids: Iterable[str]) -> list[str]:
    """Drop repeats, keeping first appearance."""
    return list(dict.fromkeys(entity_id for entity_id in entity_ids if entity_id))


def entity_ids(inputs: Mapping[str, Any], key: InputKey) -> list[str]:
    """Read one input as a list, whether or not it holds several entities.

    Callers that only ever want entities, such as diagnostics and the
    observation builder, do not need to know a key's arity.
    """
    value = inputs.get(key.value)
    if isinstance(value, list):
        return [entity_id for entity_id in value if isinstance(entity_id, str)]
    if isinstance(value, str) and value:
        return [value]
    return []


def suggest_room_inputs(
    hass: HomeAssistant, area_id: str | None
) -> dict[str, str | list[str]]:
    """Propose entities for a room from its area.

    The flow shows these pre-selected and the user confirms or clears each;
    nothing is stored until it is submitted. A single-entity input is suggested
    only when the area offers exactly one candidate, since any other number is
    a choice. Proposing is narrower than accepting: only an entity whose device
    class says what it is gets proposed.
    """
    if area_id is None:
        return {}

    candidates: dict[InputKey, list[str]] = {spec.key: [] for spec in ROOM_INPUTS}
    for entity in _area_entities(hass, area_id):
        domain = entity.entity_id.partition(".")[0]
        device_class = entity.device_class or entity.original_device_class
        for spec in ROOM_INPUTS:
            if spec.matches(domain, device_class):
                candidates[spec.key].append(entity.entity_id)

    suggestions: dict[str, str | list[str]] = {}
    for spec in ROOM_INPUTS:
        found = sorted(candidates[spec.key])
        if not found:
            continue
        if spec.multiple:
            suggestions[spec.key.value] = found
        elif len(found) == 1:
            suggestions[spec.key.value] = found[0]
    return suggestions


def _area_entities(hass: HomeAssistant, area_id: str) -> list[er.RegistryEntry]:
    """Collect the registered entities belonging to an area.

    An entity belongs to an area either directly or through its device. A
    direct assignment overrides the device's, so an entity moved out of the
    area is not dragged back in by its device. Disabled and hidden entities are
    skipped: they produce no state to read.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    found = list(er.async_entries_for_area(entity_registry, area_id))
    for device in dr.async_entries_for_area(device_registry, area_id):
        found.extend(
            entity
            for entity in er.async_entries_for_device(entity_registry, device.id)
            if entity.area_id is None
        )
    return [
        entity
        for entity in found
        if entity.disabled_by is None and entity.hidden_by is None
    ]
