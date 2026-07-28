"""Shared fixtures for the Room Advisor test suite."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.room_advisor.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading of custom integrations in every test.

    Home Assistant does not load ``custom_components`` in tests unless asked.
    Applied automatically so no individual test has to remember it.
    """


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a Room Advisor hub config entry.

    Deliberately empty: the stored shape is settled in PR 2, and a placeholder
    shape here would be a shape a later PR has to migrate away from.
    """
    return MockConfigEntry(domain=DOMAIN, title="Room Advisor", data={})
