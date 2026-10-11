"""Tests for INO-A9 config-entry setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9 import async_setup_entry, async_unload_entry
from custom_components.ino_a9.const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_setup_entry_creates_coordinator_and_forwards_platforms(hass) -> None:
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
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    with (
        patch("custom_components.ino_a9.InoA9Api", return_value=api),
        patch("custom_components.ino_a9.async_get_clientsession", return_value=Mock()),
    ):
        assert await async_setup_entry(hass, entry) is True

    assert entry.runtime_data.api is api
    assert entry.runtime_data.coordinator.data == {
        "front": {"id": "front", "connected": True, "controls": {}}
    }
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    assert await async_unload_entry(hass, entry) is True
    assert entry.runtime_data.coordinator.last_update_success is True
