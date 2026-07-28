"""Config flow for Room Advisor.

Room Advisor has exactly one hub entry per house. The hub owns the house-wide
configuration — the shared outdoor and whole-house inputs, and the default
thresholds every room inherits. Rooms are added as subentries of that hub and
may override any inherited threshold.

That split is the point of the integration rather than an implementation
detail: if each room named its own outdoor temperature sensor, eight rooms
would hold eight copies of the same answer, which is the drift the product
exists to remove.

Creating the hub asks for nothing, because the hub must be able to exist
before the entities it refers to are chosen. Shared inputs and threshold
defaults are edited afterwards through the options flow.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, NAME


class RoomAdvisorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Room Advisor hub config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm creation of the hub entry.

        Nothing is asked here. The house-wide inputs and threshold defaults
        this hub owns are edited through the options flow, so the hub can be
        created before those entities have been chosen.
        """
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title=NAME, data={})
