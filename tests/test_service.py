"""Tests for the INO-A9 intrusion schedule service."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9 import async_setup_entry, async_unload_entry
from custom_components.ino_a9.const import (
    ATTR_ENABLED,
    ATTR_END_TIME,
    ATTR_START_TIME,
    ATTR_WEEKDAYS,
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    DOMAIN,
    SERVICE_SET_INTRUSION_SCHEDULE,
)


@pytest.mark.asyncio
async def test_schedule_service_targets_camera_device(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "ino-a9-bridge.local",
            CONF_HTTP_PORT: 8080,
            CONF_RTSP_PORT: 8554,
            CONF_TOKEN: "app-token",
        },
        unique_id="ino-a9-bridge.local:8080",
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    api = Mock()
    api.async_list_cameras = AsyncMock(return_value=[{"id": "front"}])
    api.async_get_camera = AsyncMock(
        return_value={"id": "front", "connected": True, "controls": {}}
    )
    api.async_set_control = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with (
        patch("custom_components.ino_a9.InoA9Api", return_value=api),
        patch("custom_components.ino_a9.async_get_clientsession", return_value=Mock()),
    ):
        await async_setup_entry(hass, entry)

    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id, "front")},
        name="Front camera",
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_INTRUSION_SCHEDULE,
        {
            ATTR_DEVICE_ID: device.id,
            ATTR_ENABLED: True,
            ATTR_WEEKDAYS: [0, 2, 4],
            ATTR_START_TIME: "08:00:00",
            ATTR_END_TIME: "17:30:00",
        },
        blocking=True,
    )

    api.async_set_control.assert_awaited_once_with(
        "front",
        "intrusion",
        {
            "enabled": True,
            "schedule": {"days": [0, 2, 4], "start": "08:00", "end": "17:30"},
        },
    )
    await async_unload_entry(hass, entry)
