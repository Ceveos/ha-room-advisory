"""Tests for the Room Advisor config and options flows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_advisor import async_setup_entry
from custom_components.room_advisor.const import DOMAIN, NAME

SHARED_FIELDS = [
    "outdoor_temperature",
    "outdoor_humidity",
    "outdoor_air_quality",
    "rain_risk",
    "away",
]
"""The fields the hub asks for, named literally.

These are the keys stored in `entry.options["inputs"]`, so a form that offers
a different set is either a migration or a field with no translation.
"""


def _fields(result: Mapping[str, Any]) -> list[str]:
    """Read back the fields a form offers, in the order it offers them."""
    return [str(marker.schema) for marker in result["data_schema"].schema]


def _markers(result: Mapping[str, Any]) -> list[Any]:
    """Read back a form's fields as the markers carrying their suggestions."""
    return list(result["data_schema"].schema)


async def test_user_flow_creates_the_hub(hass: HomeAssistant) -> None:
    """The user flow asks for the shared inputs and then creates the hub entry.

    The entities live in options, which is what the settings flow edits, so
    there is one place they are read from.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] in (None, {})
    assert _fields(result) == SHARED_FIELDS

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"outdoor_temperature": "sensor.outside", "away": ["person.alex"]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}
    assert result["options"] == {
        "inputs": {
            "outdoor_temperature": "sensor.outside",
            "away": ["person.alex"],
        }
    }


async def test_a_hub_set_up_with_nothing_is_a_working_hub(
    hass: HomeAssistant,
) -> None:
    """Every shared input is optional, so submitting an empty form must work."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"inputs": {}}


async def test_the_settings_flow_opens_on_what_is_stored(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The shared inputs are edited where they were asked, not re-entered."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={"inputs": {"rain_risk": "binary_sensor.rain"}}
    )

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _fields(result) == SHARED_FIELDS
    suggested = {
        marker.schema: marker.description["suggested_value"]
        for marker in _markers(result)
        if marker.description
    }
    assert suggested == {"rain_risk": "binary_sensor.rain"}


async def test_the_settings_flow_stores_what_it_is_given(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Submitting the settings form replaces the shared inputs."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={"inputs": {"rain_risk": "binary_sensor.rain"}}
    )

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"outdoor_humidity": "sensor.outside_humidity"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        "inputs": {"outdoor_humidity": "sensor.outside_humidity"}
    }


async def test_a_hub_from_before_shared_inputs_opens_empty(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A hub created before this step exists has no options to read."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert _fields(result) == SHARED_FIELDS
    assert not any(marker.description for marker in _markers(result))


async def test_changing_the_shared_inputs_reloads_the_hub(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A shared input is only useful once the rooms have seen it.

    Writing options fires the entry's update listener, which is what reaches
    the rooms.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    with patch(
        "custom_components.room_advisor.async_setup_entry", wraps=async_setup_entry
    ) as setup:
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"rain_risk": "binary_sensor.rain"}
        )
        await hass.async_block_till_done()

    assert setup.call_count == 1
    assert config_entry.state is ConfigEntryState.LOADED


async def test_only_one_hub_is_allowed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A second hub is refused.

    Every setting belongs to a room, so a second hub could only ever duplicate
    the first. ``single_config_entry`` in the manifest is what enforces this;
    this test is what stops it being dropped by accident.
    """
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
