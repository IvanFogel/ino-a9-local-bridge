"""INO-A9 Local Bridge Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InoA9Api, InoA9ApiError
from .const import (
    ATTR_ENABLED,
    ATTR_END_TIME,
    ATTR_START_TIME,
    ATTR_WEEKDAYS,
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_RTSP_PORT,
    CONF_TOKEN,
    CONTROL_INTRUSION,
    DOMAIN,
    SERVICE_SET_INTRUSION_SCHEDULE,
)
from .coordinator import InoA9Coordinator

PLATFORMS: tuple[Platform, ...] = (
    Platform.CAMERA,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.BUTTON,
)


@dataclass(slots=True)
class InoA9Runtime:
    """Runtime objects shared by all INO-A9 platforms."""

    api: InoA9Api
    coordinator: InoA9Coordinator


def _validate_weekdays(value: list[int]) -> list[int]:
    """Require a deterministic, duplicate-free weekday list."""
    if value != sorted(set(value)):
        raise vol.Invalid("weekdays must be sorted and unique")
    return value


def _validate_time(value: Any) -> time:
    """Validate the app's minute-precision time format."""
    parsed = cv.time(value)
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise vol.Invalid("time must have minute precision")
    return parsed


SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(
            cv.ensure_list,
            [cv.string],
            vol.Length(min=1, max=1),
            lambda values: values[0],
        ),
        vol.Required(ATTR_ENABLED): cv.boolean,
        vol.Required(ATTR_WEEKDAYS): vol.All(
            cv.ensure_list,
            [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))],
            vol.Length(min=1, max=7),
            _validate_weekdays,
        ),
        vol.Required(ATTR_START_TIME): _validate_time,
        vol.Required(ATTR_END_TIME): _validate_time,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an INO-A9 config entry."""
    api = InoA9Api(
        host=entry.data[CONF_HOST],
        http_port=entry.data[CONF_HTTP_PORT],
        rtsp_port=entry.data[CONF_RTSP_PORT],
        token=entry.data[CONF_TOKEN],
        session=async_get_clientsession(hass),
    )
    coordinator = InoA9Coordinator(hass, api, config_entry=entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = InoA9Runtime(api=api, coordinator=coordinator)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_INTRUSION_SCHEDULE,
        _service_set_intrusion_schedule,
        schema=SERVICE_SCHEMA,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an INO-A9 config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.services.async_remove(DOMAIN, SERVICE_SET_INTRUSION_SCHEDULE)
    if hasattr(entry, "runtime_data"):
        await entry.runtime_data.coordinator.async_shutdown()
    return unload_ok


async def _service_set_intrusion_schedule(call: ServiceCall) -> None:
    """Set the complete intrusion schedule for the targeted camera device."""
    hass = call.hass
    device_id = call.data[ATTR_DEVICE_ID]
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError("The selected INO-A9 device was not found")

    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None:
            continue
        entry_key = entry.unique_id or entry.entry_id
        camera_id = next(
            (
                identifier[2]
                for identifier in device.identifiers
                if len(identifier) == 3
                and identifier[0] == DOMAIN
                and identifier[1] == str(entry_key)
                and identifier[2] in runtime.coordinator.data
            ),
            None,
        )
        if camera_id is None:
            continue
        start = call.data[ATTR_START_TIME].strftime("%H:%M")
        end = call.data[ATTR_END_TIME].strftime("%H:%M")
        if start > end:
            raise ServiceValidationError(
                "The intrusion schedule must not cross midnight"
            )
        payload = {
            ATTR_ENABLED: call.data[ATTR_ENABLED],
            "schedule": {
                "days": call.data[ATTR_WEEKDAYS],
                "start": start,
                "end": end,
            },
        }
        try:
            await runtime.api.async_set_control(camera_id, CONTROL_INTRUSION, payload)
            await runtime.coordinator.async_request_refresh()
        except InoA9ApiError as error:
            raise HomeAssistantError(
                "Unable to set the INO-A9 intrusion schedule"
            ) from error
        return

    raise ServiceValidationError("The selected device is not an INO-A9 camera")
