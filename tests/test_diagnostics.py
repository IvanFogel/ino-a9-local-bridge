"""Tests for sanitized INO-A9 diagnostics."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9 import InoA9Runtime
from custom_components.ino_a9.const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.ino_a9.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.asyncio
async def test_diagnostics_redact_app_token(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "ino-a9-bridge.local",
            CONF_HTTP_PORT: 8080,
            CONF_RTSP_PORT: 8554,
            CONF_TOKEN: "super-secret-app-token",
        },
    )
    coordinator = Mock()
    coordinator.data = {"front": {"id": "front", "connected": True, "controls": {}}}
    entry.runtime_data = InoA9Runtime(api=Mock(), coordinator=coordinator)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config_entry"][CONF_TOKEN] == "**REDACTED**"
    assert "super-secret-app-token" not in str(result)
    assert result["cameras"] == coordinator.data
