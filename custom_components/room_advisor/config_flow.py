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
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.normalized_name_base_registry import normalize_name
from homeassistant.helpers.selector import AreaSelector, TextSelector

from .const import CONF_AREA_ID, DOMAIN, NAME, SUBENTRY_TYPE_ROOM

ROOM_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AREA_ID): AreaSelector(),
        vol.Optional(CONF_NAME): TextSelector(),
    }
)


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

        ``config_entry`` is unused: every hub supports rooms.
        """
        return {SUBENTRY_TYPE_ROOM: RoomSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry.

        The hub's shared inputs and thresholds are all optional, so there is
        nothing to ask for yet.
        """
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title=NAME, data={})


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add, rename or move a room.

    A room is a name plus, optionally, an area. The area seeds the room's
    entity candidates and files its device; it is not the room's identity, so
    renaming or moving a room leaves its entities alone.
    """

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a room."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=ROOM_SCHEMA)

        room, errors = self._validate(user_input)
        if errors:
            return self._show_form("user", user_input, errors)

        return self.async_create_entry(title=room[CONF_NAME], data=room)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename a room or move it to a different area.

        The room keeps its subentry id, so its advice keeps its entity ids.
        """
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self._show_form("reconfigure", dict(subentry.data), {})

        room, errors = self._validate(user_input, subentry.subentry_id)
        if errors:
            return self._show_form("reconfigure", user_input, errors)

        return self.async_update_and_abort(
            self._get_entry(), subentry, title=room[CONF_NAME], data=room
        )

    def _show_form(
        self, step_id: str, values: dict[str, Any], errors: dict[str, str]
    ) -> SubentryFlowResult:
        """Re-show a step with what the user submitted still in place."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(ROOM_SCHEMA, values),
            errors=errors,
        )

    def _validate(
        self, user_input: dict[str, Any], subentry_id: str | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Resolve a room from the submitted form.

        An empty name falls back to the area's name. Names are compared the way
        Home Assistant compares area names, so "Great Room" and "great room"
        are the same room.
        """
        errors: dict[str, str] = {}
        area_id: str | None = user_input.get(CONF_AREA_ID)
        name = str(user_input.get(CONF_NAME) or "").strip()

        if area_id is not None:
            area = ar.async_get(self.hass).async_get_area(area_id)
            if area is None:
                errors[CONF_AREA_ID] = "unknown_area"
            elif not name:
                name = area.name

        if not name:
            if not errors:
                errors[CONF_NAME] = "name_required"
        elif self._name_taken(name, subentry_id):
            errors[CONF_NAME] = "name_taken"

        return {CONF_NAME: name, CONF_AREA_ID: area_id}, errors

    def _name_taken(self, name: str, subentry_id: str | None) -> bool:
        """Return whether another room already answers to this name."""
        normalized = normalize_name(name)
        return any(
            other_id != subentry_id
            and subentry.subentry_type == SUBENTRY_TYPE_ROOM
            and normalize_name(subentry.data[CONF_NAME]) == normalized
            for other_id, subentry in self._get_entry().subentries.items()
        )
