"""The entities a room reads, and how they are offered in the config flow.

This module is the single source of truth for the input vocabulary: the keys a
room stores, the entities each key will accept, and which keys hold several
entities. The observation layer builds its snapshot from these same keys, so a
key added here is the one place it is named.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
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
"""Where a room stores its entities, keyed by `RoomInput`.

Absent, or absent for a given key, means the input is not configured. That is
an ordinary state, not an error: every input is optional and missing ones
disable only the rules that require them.
"""


class RoomInput(StrEnum):
    """An entity a room reads.

    The values are stored in configuration, so renaming one is a migration.
    """

    INDOOR_TEMPERATURE = "indoor_temperature"
    INDOOR_CO2 = "indoor_co2"
    OCCUPANCY = "occupancy"
    WINDOW_CONTACTS = "window_contacts"
    LIGHTS = "lights"
    FAN = "fan"
    HVAC = "hvac"


@dataclass(frozen=True, slots=True)
class InputSpec:
    """What a room input accepts, and how many entities it holds."""

    key: RoomInput
    filters: tuple[EntityFilterSelectorConfig, ...]
    multiple: bool = False

    def selector(self) -> EntitySelector:
        """Build the picker this input is offered through."""
        return EntitySelector(
            EntitySelectorConfig(filter=list(self.filters), multiple=self.multiple)
        )

    def matches(self, domain: str, device_class: str | None) -> bool:
        """Return whether an entity is a candidate for this input.

        Matches on domain and device class, which is what every input here
        filters on. A filter that narrowed further would need this to narrow
        with it, or the flow would suggest an entity its own picker rejects.
        """
        return any(
            domain in _as_list(entity_filter["domain"])
            and (
                "device_class" not in entity_filter
                or device_class in _as_list(entity_filter["device_class"])
            )
            for entity_filter in self.filters
        )


def _as_list(value: str | list[str]) -> list[str]:
    """Normalise a selector filter field, which may be a string or a list."""
    return [value] if isinstance(value, str) else value


ROOM_INPUTS: Final[tuple[InputSpec, ...]] = (
    InputSpec(
        key=RoomInput.INDOOR_TEMPERATURE,
        filters=(
            EntityFilterSelectorConfig(domain="sensor", device_class="temperature"),
        ),
    ),
    InputSpec(
        key=RoomInput.INDOOR_CO2,
        filters=(
            EntityFilterSelectorConfig(domain="sensor", device_class="carbon_dioxide"),
        ),
    ),
    InputSpec(
        key=RoomInput.OCCUPANCY,
        filters=(
            EntityFilterSelectorConfig(
                domain="binary_sensor",
                device_class=["occupancy", "motion", "presence"],
            ),
        ),
    ),
    InputSpec(
        key=RoomInput.WINDOW_CONTACTS,
        filters=(
            EntityFilterSelectorConfig(
                domain="binary_sensor",
                device_class=["window", "door", "opening"],
            ),
        ),
        multiple=True,
    ),
    InputSpec(
        key=RoomInput.LIGHTS,
        filters=(EntityFilterSelectorConfig(domain="light"),),
        multiple=True,
    ),
    InputSpec(
        key=RoomInput.FAN,
        filters=(EntityFilterSelectorConfig(domain="fan"),),
    ),
    InputSpec(
        key=RoomInput.HVAC,
        filters=(EntityFilterSelectorConfig(domain="climate"),),
    ),
)


def room_inputs_schema() -> vol.Schema:
    """Build the form a room's entities are chosen on.

    Every field is optional, because every input is.
    """
    return vol.Schema(
        {vol.Optional(spec.key.value): spec.selector() for spec in ROOM_INPUTS}
    )


def clean_room_inputs(user_input: Mapping[str, Any]) -> dict[str, str | list[str]]:
    """Reduce a submitted form to what is worth storing.

    Cleared fields are dropped rather than stored empty, so "not configured"
    has one representation. Duplicates in a multi-entity input are removed,
    keeping the order the user chose.
    """
    cleaned: dict[str, str | list[str]] = {}
    for spec in ROOM_INPUTS:
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


def entity_ids(inputs: Mapping[str, Any], key: RoomInput) -> list[str]:
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
    a choice.
    """
    if area_id is None:
        return {}

    candidates: dict[RoomInput, list[str]] = {spec.key: [] for spec in ROOM_INPUTS}
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
