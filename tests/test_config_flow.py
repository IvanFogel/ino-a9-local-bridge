"""Tests for Supervisor discovery of the INO-A9 app."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_HASSIO
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from custom_components.ino_a9.const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    DOMAIN,
)


@pytest.mark.asyncio
async def test_hassio_discovery_creates_one_config_entry(
    hass, enable_custom_integrations
) -> None:
    discovery = HassioServiceInfo(
        config={
            CONF_HOST: "ino-a9-bridge.local",
            CONF_HTTP_PORT: 8080,
            CONF_RTSP_PORT: 8554,
            CONF_TOKEN: "app-token",
        },
        name="INO-A9 Local Bridge",
        slug="ino_a9_bridge",
        uuid="addon-uuid",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data=discovery,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "INO-A9 (ino-a9-bridge.local)"
    assert result["data"] == {
        CONF_HOST: "ino-a9-bridge.local",
        CONF_HTTP_PORT: 8080,
        CONF_RTSP_PORT: 8554,
        CONF_TOKEN: "app-token",
    }
    assert result["result"].unique_id == "ino-a9-bridge.local:8080"


@pytest.mark.asyncio
async def test_hassio_discovery_rejects_missing_app_endpoint(
    hass, enable_custom_integrations
) -> None:
    discovery = HassioServiceInfo(
        config={CONF_HOST: "ino-a9-bridge.local", CONF_TOKEN: "app-token"},
        name="INO-A9 Local Bridge",
        slug="ino_a9_bridge",
        uuid="addon-uuid",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data=discovery,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery"
