"""The Room Advisor integration.

Creates entities describing what is worth doing in each room right now, and
why — open a window, run a fan, turn the lights off — for automations,
dashboards and notifications to act on.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
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

    Adding, renaming and removing a room all fire this.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_room_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give every room a device, filed in its area if it has one.

    An area the user has deleted counts as no area: Home Assistant clears the
    device's area when the area goes, and writing the stored id back would undo
    that. Removing a room needs no counterpart here for the same reason — Home
    Assistant clears a subentry's devices and entities along with the subentry.
    """
    area_registry = ar.async_get(hass)
    device_registry = dr.async_get(hass)
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROOM:
            continue
        name: str = subentry.data[CONF_NAME]
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=subentry_id,
            identifiers={(DOMAIN, subentry_id)},
            manufacturer=NAME,
            model="Room",
            name=name,
        )
        area_id: str | None = subentry.data.get(CONF_AREA_ID)
        if area_id is not None and area_registry.async_get_area(area_id) is None:
            area_id = None
        if area_id is None:
            device_registry.async_update_device(device.id, name=name)
        else:
            device_registry.async_update_device(device.id, name=name, area_id=area_id)
