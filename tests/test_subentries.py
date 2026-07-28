"""Tests for adding, renaming, moving and removing rooms.

A room is a config subentry. The stored shape is the one thing that cannot be
refactored after people have installed the integration, so it is pinned here
explicitly rather than asserted loosely.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigSubentry,
)
from homeassistant.const import CONF_NAME
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


async def _submit_new_room(
    hass: HomeAssistant, entry: ConfigEntry, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Run the add-room flow to completion and return the result."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_ROOM), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return dict(result)


async def _add_room(hass: HomeAssistant, entry: ConfigEntry, **user_input: str) -> str:
    """Add a room and return its subentry id."""
    before = set(entry.subentries)
    result = await _submit_new_room(hass, entry, user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return next(iter(set(entry.subentries) - before))


def _device_for(hass: HomeAssistant, subentry_id: str) -> dr.DeviceEntry | None:
    """Return the device belonging to a room."""
    return dr.async_get(hass).async_get_device({(DOMAIN, subentry_id)})


async def test_add_room_stores_a_name_and_an_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A room stores a name and the area it was drawn from."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(hass, config_entry, area_id=area.id)
    subentry = config_entry.subentries[subentry_id]

    assert subentry.subentry_type == SUBENTRY_TYPE_ROOM
    assert subentry.title == "Office"
    assert dict(subentry.data) == {CONF_NAME: "Office", CONF_AREA_ID: area.id}


async def test_a_room_may_be_named_instead_of_its_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An explicit name wins over the area's name."""
    area = ar.async_get(hass).async_create("Kitchen")
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(
        hass, config_entry, area_id=area.id, name="Great Room"
    )

    assert config_entry.subentries[subentry_id].title == "Great Room"
    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.name == "Great Room"


async def test_a_room_need_not_have_an_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A room that matches no single area can still be created.

    The PRD says a room *normally* maps to an area. Naming one directly is the
    escape hatch for a space that does not line up with exactly one.
    """
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(hass, config_entry, name="Great Room")

    assert dict(config_entry.subentries[subentry_id].data) == {
        CONF_NAME: "Great Room",
        CONF_AREA_ID: None,
    }
    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.area_id is None


async def test_a_room_needs_a_name_or_an_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Submitting nothing is an error the user can correct in place."""
    await _setup_hub(hass, config_entry)

    result = await _submit_new_room(hass, config_entry, {})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_required"}
    assert not config_entry.subentries


async def test_add_room_for_a_deleted_area_is_an_error(
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

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_AREA_ID: "unknown_area"}
    assert not config_entry.subentries


async def test_two_rooms_may_share_an_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An area is a starting point, not an exclusive claim.

    The area only seeds entity candidates, so one large area holding two
    advisory spaces is a legitimate setup rather than a mistake to block.
    """
    area = ar.async_get(hass).async_create("Basement")
    await _setup_hub(hass, config_entry)

    first = await _add_room(hass, config_entry, area_id=area.id, name="Workshop")
    second = await _add_room(hass, config_entry, area_id=area.id, name="Home gym")

    assert first != second
    assert len(config_entry.subentries) == 2
    assert _device_for(hass, first) != _device_for(hass, second)


async def test_add_room_creates_a_device_in_the_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Each room appears as one device, filed in its own area."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)

    subentry_id = await _add_room(hass, config_entry, area_id=area.id)

    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.name == "Office"
    assert device.area_id == area.id
    assert device.config_entries_subentries[config_entry.entry_id] == {subentry_id}


async def test_reconfigure_renames_the_room_but_keeps_its_identity(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Renaming a room keeps the subentry and its device.

    The subentry id is the room's identity, so advice published for the room
    keeps its entity ids across a rename.
    """
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, area_id=area.id)
    original_device = _device_for(hass, subentry_id)
    assert original_device is not None

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: area.id, CONF_NAME: "Study"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.subentries[subentry_id].title == "Study"

    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.id == original_device.id
    assert device.name == "Study"


async def test_reconfigure_moves_the_room_to_another_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Moving a room re-files its device without recreating it."""
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    study = area_registry.async_create("Study")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, area_id=office.id, name="Desk")
    original_device = _device_for(hass, subentry_id)
    assert original_device is not None

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_AREA_ID: study.id, CONF_NAME: "Desk"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.id == original_device.id
    assert device.area_id == study.id


async def test_reconfigure_rejects_an_empty_name_without_an_area(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A room cannot be left with nothing to call it."""
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, name="Great Room")

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_ROOM),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "   "}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_required"}
    assert config_entry.subentries[subentry_id].title == "Great Room"


async def test_deleting_the_area_does_not_leave_the_device_pointing_at_it(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A deleted area is treated as no area rather than written back.

    Home Assistant clears the device's area when an area is deleted. Restoring
    the stored id on the next reload would undo that and leave the device
    filed under an area that no longer exists.
    """
    area_registry = ar.async_get(hass)
    area = area_registry.async_create("Office")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, area_id=area.id)

    area_registry.async_delete(area.id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    device = _device_for(hass, subentry_id)
    assert device is not None
    assert device.area_id is None
    assert device.name == "Office"


async def test_removing_a_room_removes_its_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Removing a room takes its device with it."""
    area = ar.async_get(hass).async_create("Office")
    await _setup_hub(hass, config_entry)
    subentry_id = await _add_room(hass, config_entry, area_id=area.id)

    assert hass.config_entries.async_remove_subentry(config_entry, subentry_id)
    await hass.async_block_till_done()

    assert not config_entry.subentries
    assert _device_for(hass, subentry_id) is None


async def test_rooms_survive_a_reload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Rooms and their devices are rebuilt from configuration on reload."""
    area_registry = ar.async_get(hass)
    office = area_registry.async_create("Office")
    study = area_registry.async_create("Study")
    await _setup_hub(hass, config_entry)
    office_id = await _add_room(hass, config_entry, area_id=office.id)
    study_id = await _add_room(hass, config_entry, area_id=study.id)

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert set(config_entry.subentries) == {office_id, study_id}
    for subentry_id in (office_id, study_id):
        assert _device_for(hass, subentry_id) is not None


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
    assert _device_for(hass, subentry_id) is None
