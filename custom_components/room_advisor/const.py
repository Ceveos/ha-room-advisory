"""Constants for the Room Advisor integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "room_advisor"

NAME: Final = "Room Advisor"

SUBENTRY_TYPE_ROOM: Final = "room"
"""Subentry type for a room.

One subentry per room, one device per subentry. The subentry id is the room's
identity: it is stable across renames and area changes, so advice published for
a room keeps its entity ids when the room is reconfigured.
"""

CONF_AREA_ID: Final = "area_id"

PLATFORMS: Final[tuple[Platform, ...]] = ()
"""Platforms forwarded on setup.

Empty until the publisher lands. The forward and unload calls in ``__init__``
are already written against this tuple, so adding a platform is a one-line
change rather than a new code path.
"""
