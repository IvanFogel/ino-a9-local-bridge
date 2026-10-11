"""Diagnostics for the INO-A9 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return useful runtime state without exposing the app token."""
    del hass
    config_entry = dict(entry.data)
    if CONF_TOKEN in config_entry:
        config_entry[CONF_TOKEN] = "**REDACTED**"
    coordinator = entry.runtime_data.coordinator
    return {
        "config_entry": config_entry,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": type(coordinator.last_exception).__name__
            if coordinator.last_exception
            else None,
        },
        "cameras": coordinator.data,
    }
