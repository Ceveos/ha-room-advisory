"""Tests for adding, moving and removing rooms.

A room is a config subentry. The stored shape is the one thing that cannot be
refactored after people have installed the integration, so it is pinned here
explicitly rather than asserted loosely.
"""

from __future__ import annotations

from types import MappingProxyType

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigSubentry,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_advisor.const import (
    CONF_AREA_ID,
    DOMAIN,
    SUBENTRY_TYPE_ROOM,
)


async def _setup_hub(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Load the hub so room changes go through a real setup."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def _add_room(hass: HomeAssistant, entry: ConfigEntry, area_id: str) -> str:
    """Add a room for an area and return the new subentry id."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: area_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    return next(
        subentry_id
        for subentry_id, subentry in entry.subentries.items()
        if subentry.data[CONF_AREA_ID] == area_id
    )


async def test_add_room_stores_the_area_and_takes_its_name(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A room stores only its area and is named after it."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(hass, config_entry, area.id)
    subentry = config_entry.subentries[subentry_id]

    assert subentry.subentry_type == SUBENTRY_TYPE_ROOM
    assert subentry.title == "Office"
    assert subentry.unique_id == area.id
    assert dict(subentry.data) == {CONF_AREA_ID: area.id}


async def test_add_room_creates_a_device_in_the_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Each room appears as one device, placed in its own area."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(hass, config_entry, area.id)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, subentry_id)})
    assert device is not None
    assert device.name == "Office"
    assert device.area_id == area.id
    assert device.config_entries_subentries[config_entry.entry_id] == {subentry_id}


async def test_second_room_for_the_same_area_is_rejected(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An area maps to at most one room."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)
    await _add_room(hass, config_entry, area.id)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: area.id}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(config_entry.subentries) == 1


async def test_add_room_for_a_deleted_area_is_rejected(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An area that disappears mid-flow does not produce a nameless room."""
    area_registry = ar.async_get(hass)
    area = area_registry.async_create("Office")
    await _setup_hub(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
    )
    area_registry.async_delete(area.id)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: area.id}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_area"
    assert not config_entry.subentries


async def test_reconfigure_moves_the_room_but_keeps_its_identity(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Moving a room to another area keeps the subentry and its device.

    The subentry id is the room's identity, so advice published for the room
    keeps its entity ids across the move.
    """
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    study = area_registry.async_create("Study")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, office.id)
    original_device = dr.async_get(hass).async_get_device({(DOMAIN, subentry_id)})
    assert original_device is not None

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: study.id}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = config_entry.subentries[subentry_id]
    assert subentry.title == "Study"
    assert subentry.unique_id == study.id
    assert dict(subentry.data) == {CONF_AREA_ID: study.id}

    device = dr.async_get(hass).async_get_device({(DOMAIN, subentry_id)})
    assert device is not None
    assert device.id == original_device.id
    assert device.area_id == study.id
    assert device.name == "Study"


async def test_reconfigure_onto_an_occupied_area_is_rejected(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A room cannot be moved onto an area another room already holds."""
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    study = area_registry.async_create("Study")
    await _setup_hub(hass, config_entry)
    office_id = await _add_room(hass, config_entry, office.id)
    await _add_room(hass, config_entry, study.id)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": office_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: study.id}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.subentries[office_id].unique_id == office.id


async def test_removing_a_room_removes_its_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Removing a room takes its device with it."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, area.id)

    assert hass.config_entries.async_remove_subentry(config_entry, subentry_id)
    await hass.async_block_till_done()

    assert not config_entry.subentries
    assert dr.async_get(hass).async_get_device({(DOMAIN, subentry_id)}) is None


async def test_rooms_survive_a_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Rooms and their devices are rebuilt from configuration on reload."""
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    study = area_registry.async_create("Study")
    await _setup_hub(hass, config_entry)
    office_id = await _add_room(hass, config_entry, office.id)
    study_id = await _add_room(hass, config_entry, study.id)

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert set(config_entry.subentries) == {office_id, study_id}
    device_registry = dr.async_get(hass)
    for subentry_id in (office_id, study_id):
        assert device_registry.async_get_device({(DOMAIN, subentry_id)}) is not None


async def test_a_non_room_subentry_gets_no_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Only room subentries become devices.

    Nothing else creates subentries yet, so this pins the guard rather than an
    existing behaviour: a future subentry type must opt in to a device.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_add_subentry(
        config_entry,
        ConfigSubentry(
            data=MappingProxyType({}),
            subentry_type="not_a_room",
            title="Something else",
            unique_id=None,
        ),
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = next(iter(config_entry.subentries))
    assert dr.async_get(hass).async_get_device({(DOMAIN, subentry_id)}) is None
