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

    Adding, reconfiguring and removing a room all fire this. Reloading rather
    than patching state in place means there is one path that builds a room
    from its configuration, so a running instance and a freshly started one
    cannot disagree.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_room_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give every room a device.

    A room that names an area is placed in it. A room without one is left where
    it is, so the user can file it themselves. An area the user has since
    deleted is treated as no area at all rather than written back, which would
    undo Home Assistant's own cleanup and leave the device pointing at nothing.

    Removing a room needs no counterpart here: Home Assistant clears devices and
    entities belonging to a subentry when the subentry goes.
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
