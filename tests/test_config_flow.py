"""Tests for the Room Advisor config flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_advisor.const import DOMAIN, NAME


async def test_user_flow_creates_the_hub(hass: HomeAssistant) -> None:
    """The user flow shows a confirmation form and then creates the hub entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] in (None, {})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}


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
