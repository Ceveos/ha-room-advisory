"""Constants for the Room Advisor integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "room_advisor"

NAME: Final = "Room Advisor"

PLATFORMS: Final[tuple[Platform, ...]] = ()
"""Platforms forwarded on setup.

Empty until the publisher lands. The forward and unload calls in ``__init__``
are already written against this tuple, so adding a platform is a one-line
change rather than a new code path.
"""
