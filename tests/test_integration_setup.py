"""End-to-end config-entry setup coverage for native entities."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9.const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_config_entry_setup_creates_camera_and_control_entities(
    hass, enable_custom_integrations
) -> None:
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
    api = Mock()
    api.async_list_cameras = AsyncMock(return_value=[{"id": "front"}])
    api.async_get_camera = AsyncMock(
        return_value={
            "id": "front",
            "name": "Front camera",
            "connected": True,
            "media": {"has_frame": True, "has_audio": True},
            "controls": {
                "led": {"value": False, "known": True, "source": "persisted"},
                "night_vision": {
                    "value": "automatic",
                    "known": True,
                    "source": "readback",
                },
                "flip": {"value": "upright", "known": True, "source": "readback"},
                "video_quality": {
                    "value": "hd",
                    "known": True,
                    "source": "persisted",
                },
                "motion": {"value": "medium", "known": True, "source": "persisted"},
                "intrusion": {
                    "value": {
                        "enabled": False,
                        "schedule": {"days": [0], "start": "08:00", "end": "17:00"},
                    },
                    "known": True,
                    "source": "persisted",
                },
            },
        }
    )
    api.rtsp_url = Mock(return_value="rtsp://ino-a9-bridge:8554/ino_a9_front")

    with (
        patch("custom_components.ino_a9.InoA9Api", return_value=api),
        patch("custom_components.ino_a9.async_get_clientsession", return_value=Mock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = [
        entity
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id
    ]
    assert len(entities) == 8
    assert {entity.domain for entity in entities} == {
        "camera",
        "switch",
        "select",
        "button",
    }
    assert hass.services.has_service(DOMAIN, "set_intrusion_schedule")

    assert await hass.config_entries.async_unload(entry.entry_id)
