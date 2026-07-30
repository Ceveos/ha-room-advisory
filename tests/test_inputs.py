"""Tests for the room input vocabulary.

The keys here are stored in configuration and read by the observation layer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_advisor import inputs as inputs_module
from custom_components.room_advisor.inputs import (
    ROOM_INPUTS,
    RoomInput,
    clean_room_inputs,
    entity_ids,
    room_inputs_schema,
    suggest_room_inputs,
)


def test_every_input_is_offered_exactly_once() -> None:
    """A key with no field could never be set, and a duplicate would shadow."""
    assert [spec.key for spec in ROOM_INPUTS] == list(RoomInput)


def test_the_stored_keys_are_what_they_are() -> None:
    """These strings are in people's configuration. Changing one is a migration.

    Stated literally rather than derived from the enum, so that renaming a
    member fails here instead of silently orphaning stored entities.
    """
    assert {input_key.value for input_key in RoomInput} == {
        "indoor_temperature",
        "indoor_co2",
        "occupancy",
        "window_contacts",
        "lights",
        "fan",
        "hvac",
    }


def test_the_form_offers_exactly_the_translated_fields() -> None:
    """A field with no translation renders as a raw key.

    `strings.json` names the fields by hand, so it can drift from the inputs it
    describes without anything else noticing.
    """
    strings = json.loads(
        (Path(inputs_module.__file__).parent / "strings.json").read_text(
            encoding="utf-8"
        )
    )
    step = strings["config_subentries"]["room"]["step"]["inputs"]
    expected = [spec.key.value for spec in ROOM_INPUTS]

    assert list(step["data"]) == expected
    assert list(step["data_description"]) == expected


def test_cleaned_inputs_are_json_native() -> None:
    """Subentry data is stored as JSON, so an enum member must not reach it.

    `RoomInput` is a `StrEnum` and compares equal to its own value, so an
    equality assertion cannot catch this.
    """
    cleaned = clean_room_inputs({RoomInput.FAN: "fan.a", RoomInput.LIGHTS: ["light.a"]})

    assert all(type(key) is str for key in cleaned)
    assert json.loads(json.dumps(cleaned)) == cleaned


def test_every_filter_names_a_domain() -> None:
    """Suggestion matching reads the domain of every filter."""
    assert all(
        "domain" in entity_filter
        for spec in ROOM_INPUTS
        for entity_filter in spec.filters
    )


def test_every_field_is_optional() -> None:
    """Every input is optional, so no field may block the form."""
    assert room_inputs_schema()({}) == {}
    assert all(
        isinstance(marker, vol.Optional) for marker in room_inputs_schema().schema
    )


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        pytest.param({}, {}, id="nothing submitted"),
        pytest.param(
            {RoomInput.INDOOR_TEMPERATURE: "sensor.a"},
            {RoomInput.INDOOR_TEMPERATURE: "sensor.a"},
            id="single entity kept",
        ),
        pytest.param(
            {RoomInput.INDOOR_TEMPERATURE: ""},
            {},
            id="cleared single field dropped",
        ),
        pytest.param(
            {RoomInput.LIGHTS: []},
            {},
            id="cleared multi field dropped",
        ),
        pytest.param(
            {RoomInput.LIGHTS: ["light.a", "light.b", "light.a"]},
            {RoomInput.LIGHTS: ["light.a", "light.b"]},
            id="repeats dropped, order kept",
        ),
        pytest.param(
            {"not_an_input": "sensor.a"},
            {},
            id="unknown key dropped",
        ),
    ],
)
def test_clean_room_inputs(
    submitted: dict[str, object], expected: dict[str, object]
) -> None:
    """Cleared fields are dropped, so "not configured" has one representation."""
    assert clean_room_inputs(submitted) == expected


@pytest.mark.parametrize(
    ("stored", "key", "expected"),
    [
        pytest.param({}, RoomInput.LIGHTS, [], id="absent"),
        pytest.param(
            {RoomInput.FAN: "fan.a"}, RoomInput.FAN, ["fan.a"], id="single as list"
        ),
        pytest.param(
            {RoomInput.LIGHTS: ["light.a", "light.b"]},
            RoomInput.LIGHTS,
            ["light.a", "light.b"],
            id="already a list",
        ),
    ],
)
def test_entity_ids_reads_any_input_as_a_list(
    stored: dict[str, object], key: RoomInput, expected: list[str]
) -> None:
    """Callers that only want entities do not need to know a key's arity."""
    assert entity_ids(stored, key) == expected


def _register(
    hass: HomeAssistant,
    entity_id: str,
    *,
    device_class: str | None = None,
    area_id: str | None = None,
    device_id: str | None = None,
) -> er.RegistryEntry:
    """Register an entity, optionally in an area or on a device."""
    domain, _, object_id = entity_id.partition(".")
    entry = er.async_get(hass).async_get_or_create(
        domain,
        "test",
        object_id,
        suggested_object_id=object_id,
        original_device_class=device_class,
        device_id=device_id,
    )
    if area_id is not None:
        entry = er.async_get(hass).async_update_entity(entry.entity_id, area_id=area_id)
    return entry


async def test_no_area_means_no_suggestions(hass: HomeAssistant) -> None:
    """A room named rather than drawn from an area has nothing to suggest from."""
    assert suggest_room_inputs(hass, None) == {}


async def test_suggestions_match_domain_and_device_class(
    hass: HomeAssistant,
) -> None:
    """Only entities the picker would have accepted are suggested."""
    area = ar.async_get(hass).async_create("Office")
    _register(hass, "sensor.temperature", device_class="temperature", area_id=area.id)
    _register(hass, "sensor.power", device_class="power", area_id=area.id)
    _register(hass, "light.desk", area_id=area.id)

    assert suggest_room_inputs(hass, area.id) == {
        RoomInput.INDOOR_TEMPERATURE: "sensor.temperature",
        RoomInput.LIGHTS: ["light.desk"],
    }


async def test_an_ambiguous_single_input_is_not_guessed(hass: HomeAssistant) -> None:
    """Two thermometers is a choice only the user can make.

    A multi-entity input has no such ambiguity and takes both.
    """
    area = ar.async_get(hass).async_create("Office")
    _register(hass, "sensor.desk", device_class="temperature", area_id=area.id)
    _register(hass, "sensor.wall", device_class="temperature", area_id=area.id)
    _register(hass, "binary_sensor.left", device_class="window", area_id=area.id)
    _register(hass, "binary_sensor.right", device_class="window", area_id=area.id)

    assert suggest_room_inputs(hass, area.id) == {
        RoomInput.WINDOW_CONTACTS: ["binary_sensor.left", "binary_sensor.right"]
    }


async def test_entities_are_found_through_their_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An entity usually gets its area from the device it belongs to."""
    config_entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Office")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "thermostat")},
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    _register(hass, "climate.office", device_id=device.id)

    assert suggest_room_inputs(hass, area.id) == {RoomInput.HVAC: "climate.office"}


async def test_an_entity_moved_out_of_the_area_is_not_dragged_back(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An entity's own area overrides its device's."""
    config_entry.add_to_hass(hass)
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    hall = area_registry.async_create("Hall")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "thermostat")},
    )
    dr.async_get(hass).async_update_device(device.id, area_id=office.id)
    _register(hass, "climate.office", device_id=device.id, area_id=hall.id)

    assert suggest_room_inputs(hass, office.id) == {}
    assert suggest_room_inputs(hass, hall.id) == {RoomInput.HVAC: "climate.office"}


async def test_a_disabled_entity_is_not_suggested(hass: HomeAssistant) -> None:
    """A disabled entity produces no state to read."""
    area = ar.async_get(hass).async_create("Office")
    entry = _register(
        hass, "sensor.temperature", device_class="temperature", area_id=area.id
    )
    er.async_get(hass).async_update_entity(
        entry.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )

    assert suggest_room_inputs(hass, area.id) == {}


async def test_a_hidden_entity_is_not_suggested(hass: HomeAssistant) -> None:
    """Hiding an entity is as clear a statement as disabling it."""
    area = ar.async_get(hass).async_create("Office")
    entry = _register(
        hass, "sensor.temperature", device_class="temperature", area_id=area.id
    )
    er.async_get(hass).async_update_entity(
        entry.entity_id, hidden_by=er.RegistryEntryHider.USER
    )

    assert suggest_room_inputs(hass, area.id) == {}
