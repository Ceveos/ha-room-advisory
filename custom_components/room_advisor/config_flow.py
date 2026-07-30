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
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
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
    ROOM_INPUTS,
    SHARED_INPUTS,
    clean_inputs,
    inputs_schema,
    suggest_room_inputs,
)

ADD_ROOM_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AREA_ID): AreaSelector(),
        vol.Optional(CONF_NAME): TextSelector(),
    }
)

EDIT_ROOM_SCHEMA = vol.Schema({vol.Optional(CONF_AREA_ID): AreaSelector()})
"""Editing a room offers no name field.

The room is named by its subentry title, which Home Assistant renames itself.
"""


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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> OptionsFlow:
        """Return the flow that edits the shared inputs.

        ``config_entry`` is unused: there is one hub and the flow reaches it
        itself.
        """
        return RoomAdvisorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry and collect the shared inputs.

        Everything asked here is optional, and can be changed afterwards
        through the hub's own settings.
        """
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=inputs_schema(SHARED_INPUTS)
            )

        return self.async_create_entry(
            title=NAME,
            data={},
            options={CONF_INPUTS: clean_inputs(user_input, SHARED_INPUTS)},
        )


class RoomAdvisorOptionsFlow(OptionsFlow):
    """Edit the inputs every room shares.

    They are asked during setup, so this is where they are changed rather than
    where they are first met. Writing options reloads the hub, which is how a
    change reaches the rooms.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the shared inputs as they stand, and store what comes back."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=self.add_suggested_values_to_schema(
                    inputs_schema(SHARED_INPUTS),
                    dict(self.config_entry.options.get(CONF_INPUTS, {})),
                ),
            )

        return self.async_create_entry(
            data={CONF_INPUTS: clean_inputs(user_input, SHARED_INPUTS)}
        )


class RoomSubentryFlow(ConfigSubentryFlow):
    """Add or edit a room.

    A room is named by its subentry title, so Home Assistant's own rename is
    the only way to rename one. What the room stores is the area it is drawn
    from and the entities it reads. The area seeds the entity suggestions and
    files the room's device; it is not the room's identity, so renaming or
    moving a room leaves its entities alone.
    """

    _name: str
    _area_id: str | None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name the new room and say which area it covers."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=ADD_ROOM_SCHEMA)

        errors = self._validate(user_input)
        if errors:
            return self._show_form("user", user_input, errors)

        return await self.async_step_inputs()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Move a room to a different area, or change what it reads.

        The room keeps its subentry id, so its advice keeps its entity ids.
        """
        subentry = self._get_reconfigure_subentry()
        if user_input is None:
            return self._show_form(
                "reconfigure", {CONF_AREA_ID: subentry.data.get(CONF_AREA_ID)}, {}
            )

        errors = self._validate(user_input, subentry)
        if errors:
            return self._show_form("reconfigure", user_input, errors)

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
                    inputs_schema(ROOM_INPUTS), self._suggested_inputs()
                ),
            )

        room = {
            CONF_AREA_ID: self._area_id,
            CONF_INPUTS: clean_inputs(user_input, ROOM_INPUTS),
        }
        if self.source != SOURCE_RECONFIGURE:
            return self.async_create_entry(title=self._name, data=room)

        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
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
        return suggest_room_inputs(self.hass, self._area_id)

    def _show_form(
        self, step_id: str, values: dict[str, Any], errors: dict[str, str]
    ) -> SubentryFlowResult:
        """Re-show a step with what the user submitted still in place."""
        schema = ADD_ROOM_SCHEMA if step_id == "user" else EDIT_ROOM_SCHEMA
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, values),
            errors=errors,
        )

    def _validate(
        self, user_input: dict[str, Any], subentry: ConfigSubentry | None = None
    ) -> dict[str, str]:
        """Resolve the room's name and area.

        Adding a room asks for a name. Editing one does not: the name is the
        subentry title, which Home Assistant renames itself. On success both
        are held for the entity step, which is where the room is written.
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

        if subentry is not None:
            name = subentry.title
        elif not name:
            if not errors:
                errors[CONF_NAME] = "name_required"
        elif self._name_taken(name):
            errors[CONF_NAME] = "name_taken"

        if not errors:
            self._name = name
            self._area_id = area_id
        return errors

    def _name_taken(self, name: str) -> bool:
        """Return whether a room already answers to this name.

        Only adding a room asks. Home Assistant's own rename writes the title
        without consulting us, so matching names are possible; a room's
        identity is its subentry id, never its name.
        """
        normalized = normalize_name(name)
        return any(
            other.subentry_type == SUBENTRY_TYPE_ROOM
            and normalize_name(other.title) == normalized
            for other in self._get_entry().subentries.values()
        )
