"""The Room Advisor integration.

Room Advisor reads a room's existing Home Assistant entities and publishes what
is advisable there, and why. It never performs the action.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Room Advisor from a config entry."""
    _LOGGER.debug("Setting up config entry %s", entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Room Advisor config entry."""
    _LOGGER.debug("Unloading config entry %s", entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
