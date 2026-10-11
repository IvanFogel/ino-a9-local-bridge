"""Config flow for the INO-A9 Home Assistant app."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import CONF_HOST, CONF_HTTP_PORT, CONF_RTSP_PORT, CONF_TOKEN, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_HTTP_PORT, default=8080): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_RTSP_PORT, default=8554): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_TOKEN): str,
    }
)


class InoA9ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle manual and Supervisor-discovered app configuration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        data = _validated_data(user_input)
        if data is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors={"base": "invalid_discovery"},
            )

        await self.async_set_unique_id(_unique_id(data))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=_title(data[CONF_HOST]), data=data)

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle discovery data published by the INO-A9 app."""
        config = getattr(discovery_info, "config", None)
        if not isinstance(config, Mapping):
            return self.async_abort(reason="invalid_discovery")

        data = _validated_data(config)
        if data is None:
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(_unique_id(data))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=_title(data[CONF_HOST]), data=data)


def _validated_data(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return only the supported, well-typed app connection data."""
    host = raw.get(CONF_HOST)
    http_port = raw.get(CONF_HTTP_PORT)
    rtsp_port = raw.get(CONF_RTSP_PORT)
    token = raw.get(CONF_TOKEN)
    if (
        not isinstance(host, str)
        or not host.strip()
        or type(http_port) is not int
        or not 1 <= http_port <= 65535
        or type(rtsp_port) is not int
        or not 1 <= rtsp_port <= 65535
        or not isinstance(token, str)
        or not token
    ):
        return None
    return {
        CONF_HOST: host.strip(),
        CONF_HTTP_PORT: http_port,
        CONF_RTSP_PORT: rtsp_port,
        CONF_TOKEN: token,
    }


def _unique_id(data: Mapping[str, Any]) -> str:
    """Build an endpoint-stable unique ID."""
    return f"{data[CONF_HOST]}:{data[CONF_HTTP_PORT]}"


def _title(host: str) -> str:
    """Build a stable human-readable entry title."""
    return f"INO-A9 ({host})"
