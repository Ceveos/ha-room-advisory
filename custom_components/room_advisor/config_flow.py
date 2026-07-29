"""Config flow for Room Advisor.

One hub per house, holding the shared inputs and default thresholds that every
room inherits. Rooms are added as subentries, each choosing the entities it
reads and overriding what it inherits.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
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
from .inputs import (
    CONF_INPUTS,
    clean_room_inputs,
    room_inputs_schema,
    suggest_room_inputs,
)

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
    """Add or edit a room.

    A room is a name, optionally an area, and the entities it reads. The area
    seeds the room's entity suggestions and files its device; it is not the
    room's identity, so renaming or moving a room leaves its entities alone.
    """

    _room: dict[str, Any]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the new room and say which area it covers."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=ROOM_SCHEMA)

        room, errors = self._validate(user_input)
        if errors:
            return self._show_form("user", user_input, errors)

        self._room = room
        return await self.async_step_inputs()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename a room, move it, or change which entities it reads.

        The room keeps its subentry id, so its advice keeps its entity ids.
        """
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self._show_form("reconfigure", dict(subentry.data), {})

        room, errors = self._validate(user_input, subentry.subentry_id)
        if errors:
            return self._show_form("reconfigure", user_input, errors)

        self._room = room
        return await self.async_step_inputs()

    async def async_step_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose the entities the room reads.

        Every field is optional. A missing input disables only the rules that
        need it, so a room with a thermometer and nothing else is a working
        room.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="inputs",
                data_schema=self.add_suggested_values_to_schema(
                    room_inputs_schema(), self._suggested_inputs()
                ),
            )

        room = {**self._room, CONF_INPUTS: clean_room_inputs(user_input)}
        if self.source != SOURCE_RECONFIGURE:
            return self.async_create_entry(title=room[CONF_NAME], data=room)

        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            title=room[CONF_NAME],
            data=room,
        )

    def _suggested_inputs(self) -> dict[str, Any]:
        """Decide what the entity form opens with.

        A room that has already been through this step opens with exactly what
        it stores, including the fields the user cleared. A room that has not —
        a new room, or one added before this step existed — opens with what its
        area offers.
        """
        if self.source == SOURCE_RECONFIGURE:
            stored = self._get_reconfigure_subentry().data.get(CONF_INPUTS)
            if stored is not None:
                return dict(stored)
        return suggest_room_inputs(self.hass, self._room[CONF_AREA_ID])

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
