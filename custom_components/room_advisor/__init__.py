"""The Room Advisor integration.

Creates entities describing what is worth doing in each room right now, and
why — open a window, run a fan, turn the lights off — for automations,
dashboards and notifications to act on.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_AREA_ID, DOMAIN, NAME, PLATFORMS, SUBENTRY_TYPE_ROOM

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Room Advisor from a config entry."""
    _LOGGER.debug("Setting up config entry %s", entry.entry_id)
    _async_register_room_devices(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_config_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Room Advisor config entry."""
    _LOGGER.debug("Unloading config entry %s", entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_config_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the hub or any room changes.

    Adding, reconfiguring and removing a room all fire this. Reloading rather
    than patching state in place means there is one path that builds a room
    from its configuration, so a running instance and a freshly started one
    cannot disagree.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_room_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give every room a device, placed in the area the room is anchored to.

    Removing a room does not need a counterpart here: Home Assistant clears
    devices and entities belonging to a subentry when the subentry goes.
    """
    device_registry = dr.async_get(hass)
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROOM:
            continue
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=subentry_id,
            identifiers={(DOMAIN, subentry_id)},
            manufacturer=NAME,
            model="Room",
            name=subentry.title,
        )
        device_registry.async_update_device(
            device.id, area_id=subentry.data[CONF_AREA_ID], name=subentry.title
        )
