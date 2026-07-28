"""Config flow for Room Advisor.

One hub per house, holding the shared inputs and default thresholds that every
room inherits. Rooms are added as subentries and may override what they
inherit.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import AreaSelector

from .const import CONF_AREA_ID, DOMAIN, NAME, SUBENTRY_TYPE_ROOM

ROOM_SCHEMA = vol.Schema({vol.Required(CONF_AREA_ID): AreaSelector()})


class RoomAdvisorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Room Advisor hub config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types the hub supports.

        The signature is set by Home Assistant; the entry is unused because
        every hub supports rooms.
        """
        return {SUBENTRY_TYPE_ROOM: RoomSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry.

        The shared inputs and thresholds the hub holds are all optional and are
        asked for here; the fields themselves land with the configuration work.
        """
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title=NAME, data={})


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a room.

    A room is anchored to an area. The area is what lets Room Advisor find the
    room's existing entities, and it is the only thing asked for here — every
    other setting is inherited from the hub until the room overrides it.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a room."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=ROOM_SCHEMA)

        area_id: str = user_input[CONF_AREA_ID]
        return self.async_create_entry(
            title=self._area_name(area_id),
            data={CONF_AREA_ID: area_id},
            unique_id=area_id,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Move an existing room to a different area.

        The room keeps its subentry id, so its advice keeps its entity ids.
        """
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(
                    ROOM_SCHEMA, subentry.data
                ),
            )

        area_id: str = user_input[CONF_AREA_ID]
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            title=self._area_name(area_id),
            data={CONF_AREA_ID: area_id},
            unique_id=area_id,
        )

    def _area_name(self, area_id: str) -> str:
        """Return the name of an area, or abort if it has gone away."""
        area = ar.async_get(self.hass).async_get_area(area_id)
        if area is None:
            raise AbortFlow("unknown_area")
        return area.name
