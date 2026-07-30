"""Tests holding the builder's borrowed vocabulary against its sources.

The builder writes out the states and attributes of other integrations rather
than importing them, so that reading a room pulls in no component but our own.
That is only safe while the copies are checked, which is what this file does.
"""

from __future__ import annotations

from homeassistant.components.alarm_control_panel.const import (
    DOMAIN as ALARM_DOMAIN,
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.components.climate.const import ATTR_HVAC_ACTION, HVACAction
from homeassistant.components.weather.const import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_TEMPERATURE_UNIT,
)
from homeassistant.components.weather.const import DOMAIN as WEATHER_DOMAIN

from custom_components.room_advisor.observations import builder


def test_the_domains_are_the_domains() -> None:
    """A domain we misspell is a source we silently read the wrong way."""
    assert builder._WEATHER_DOMAIN == WEATHER_DOMAIN
    assert builder._ALARM_DOMAIN == ALARM_DOMAIN


def test_the_attributes_are_the_attributes() -> None:
    """An attribute we misspell reads as absent, which is a usable answer."""
    assert builder._ATTR_WEATHER_TEMPERATURE == ATTR_WEATHER_TEMPERATURE
    assert builder._ATTR_WEATHER_TEMPERATURE_UNIT == ATTR_WEATHER_TEMPERATURE_UNIT
    assert builder._ATTR_WEATHER_HUMIDITY == ATTR_WEATHER_HUMIDITY
    assert builder._ATTR_HVAC_ACTION == ATTR_HVAC_ACTION


def test_every_hvac_action_is_accounted_for() -> None:
    """An action we do not know is refused, so a new one must be classified."""
    assert sorted(builder._HVAC_ACTIONS) == sorted(
        action.value for action in HVACAction
    )
    assert builder._CONDITIONING_ACTIONS <= builder._HVAC_ACTIONS


def test_every_alarm_state_is_accounted_for() -> None:
    """An armed state we do not know is refused rather than read as at home."""
    assert sorted(builder._ALARM_STATES) == sorted(
        state.value for state in AlarmControlPanelState
    )
    assert builder._AWAY_ALARM_STATES <= builder._ALARM_STATES
