"""Constants for the Room Advisor integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "room_advisor"

NAME: Final = "Room Advisor"

SUBENTRY_TYPE_ROOM: Final = "room"
"""Subentry type for a room.

The subentry id is the room's identity, and is stable across renames and area
changes.
"""

CONF_AREA_ID: Final = "area_id"
"""The area a room is drawn from, if any.

Seeds the room's entity candidates and files its device. Optional, and not an
identity.
"""

PLATFORMS: Final[tuple[Platform, ...]] = ()
"""Platforms forwarded on setup."""
