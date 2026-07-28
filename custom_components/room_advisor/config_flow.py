"""Config flow for Room Advisor.

Room Advisor has exactly one hub entry. It carries no options of its own: every
setting belongs to a room, and rooms are added as subentries of this hub.
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
        """Confirm creation of the single hub entry.

        There is nothing to ask for. The form exists so the user gets a
        confirmation step rather than an entry appearing without explanation.
        """
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title=NAME, data={})
