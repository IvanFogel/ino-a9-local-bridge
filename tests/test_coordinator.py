"""Tests for the INO-A9 data coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.ino_a9.coordinator import InoA9Coordinator


@pytest.mark.asyncio
async def test_coordinator_polls_multiple_camera_details(hass) -> None:
    api = AsyncMock()
    api.async_list_cameras.return_value = [
        {"id": "front", "connected": True},
        {"id": "garage", "connected": False},
    ]
    api.async_get_camera.side_effect = [
        {"id": "front", "connected": True, "controls": {}},
        {"id": "garage", "connected": False, "controls": {}},
    ]
    coordinator = InoA9Coordinator(hass, api)

    coordinator.data = await coordinator._async_update_data()

    assert set(coordinator.data) == {"front", "garage"}
    assert coordinator.data["garage"]["connected"] is False
    assert api.async_get_camera.await_count == 2


@pytest.mark.asyncio
async def test_coordinator_translates_app_error_to_update_failed(hass) -> None:
    api = AsyncMock()
    api.async_list_cameras.side_effect = RuntimeError("app unavailable")
    coordinator = InoA9Coordinator(hass, api)

    with pytest.raises(UpdateFailed, match="Unable to update INO-A9 cameras"):
        await coordinator._async_update_data()
