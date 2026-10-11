"""Tests for native INO-A9 Home Assistant entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9.button import InoA9RebootButton
from custom_components.ino_a9.camera import InoA9Camera
from custom_components.ino_a9.const import (
    CONTROL_INTRUSION,
    CONTROL_LED,
    CONTROL_NIGHT_VISION,
    DOMAIN,
)
from custom_components.ino_a9.coordinator import InoA9Coordinator
from custom_components.ino_a9.select import InoA9Select
from custom_components.ino_a9.switch import InoA9Switch


def _coordinator(hass):
    api = AsyncMock()
    api.async_get_snapshot.return_value = b"jpeg"
    api.rtsp_url = Mock(return_value="rtsp://ino-a9-bridge:8554/ino_a9_front")
    coordinator = InoA9Coordinator(hass, api)
    coordinator.data = {
        "front": {
            "id": "front",
            "name": "Front camera",
            "connected": True,
            "media": {"has_frame": True, "has_audio": True},
            "controls": {
                CONTROL_LED: {"value": False, "known": True, "source": "persisted"},
                CONTROL_NIGHT_VISION: {
                    "value": "automatic",
                    "known": True,
                    "source": "persisted",
                },
                CONTROL_INTRUSION: {
                    "value": {
                        "enabled": False,
                        "schedule": {
                            "days": [0, 1, 2, 3, 4],
                            "start": "08:00",
                            "end": "22:00",
                        },
                    },
                    "known": True,
                    "source": "persisted",
                },
            },
        }
    }
    coordinator.last_update_success = True
    coordinator.async_request_refresh = AsyncMock()
    entry = MockConfigEntry(domain=DOMAIN, unique_id="ino-a9-bridge.local:8080")
    return coordinator, api, entry


@pytest.mark.asyncio
async def test_camera_exposes_snapshot_rtsp_and_shared_device(hass) -> None:
    coordinator, api, entry = _coordinator(hass)
    camera = InoA9Camera(coordinator, entry, "front")

    assert camera.unique_id == f"{DOMAIN}_{entry.entry_id}_front_camera"
    assert camera.name == "Camera"
    assert camera.device_info["identifiers"] == {(DOMAIN, entry.unique_id, "front")}
    assert await camera.async_camera_image() == b"jpeg"
    assert await camera.stream_source() == "rtsp://ino-a9-bridge:8554/ino_a9_front"
    api.async_get_snapshot.assert_awaited_once_with("front")


@pytest.mark.asyncio
async def test_switches_and_select_write_controls(hass) -> None:
    coordinator, api, entry = _coordinator(hass)
    led = InoA9Switch(coordinator, entry, "front", CONTROL_LED)
    intrusion = InoA9Switch(coordinator, entry, "front", CONTROL_INTRUSION)
    night = InoA9Select(coordinator, entry, "front", CONTROL_NIGHT_VISION)

    assert led.is_on is False
    await led.async_turn_on()
    await intrusion.async_turn_on()
    await night.async_select_option("enabled")

    assert api.async_set_control.await_count == 3
    assert api.async_set_control.await_args_list[0].args == (
        "front",
        CONTROL_LED,
        {"value": True},
    )
    assert api.async_set_control.await_args_list[1].args == (
        "front",
        CONTROL_INTRUSION,
        {
            "enabled": True,
            "schedule": {"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "22:00"},
        },
    )
    assert api.async_set_control.await_args_list[2].args == (
        "front",
        CONTROL_NIGHT_VISION,
        {"value": "enabled"},
    )
    assert coordinator.async_request_refresh.await_count == 3


@pytest.mark.asyncio
async def test_reboot_button_uses_app_command(hass) -> None:
    coordinator, api, entry = _coordinator(hass)
    button = InoA9RebootButton(coordinator, entry, "front")

    await button.async_press()

    api.async_reboot.assert_awaited_once_with("front")
