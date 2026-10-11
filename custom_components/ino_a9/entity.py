"""Shared entity helpers for the INO-A9 integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import InoA9ApiError
from .const import DOMAIN
from .coordinator import InoA9Coordinator


class InoA9Entity(CoordinatorEntity[InoA9Coordinator]):
    """Base entity bound to one camera in the shared app coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InoA9Coordinator,
        entry: Any,
        camera_id: str,
        entity_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.camera_id = camera_id
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{camera_id}_{entity_suffix}"
        self._attr_name = name
        device_name = self._camera_name()
        entry_key = entry.unique_id or entry.entry_id
        self._attr_device_info: DeviceInfo = {
            "identifiers": {(DOMAIN, str(entry_key), camera_id)},
            "name": device_name,
            "manufacturer": "INO-A9",
            "model": "Local Bridge Camera",
        }

    @property
    def camera_data(self) -> dict[str, Any]:
        """Return the current detail document for this camera."""
        value = self.coordinator.data.get(self.camera_id, {})
        return value if isinstance(value, dict) else {}

    @property
    def available(self) -> bool:
        """Report availability only when the app has a connected camera."""
        return bool(
            self.coordinator.last_update_success
            and self.camera_data.get("connected") is True
        )

    def _camera_name(self) -> str:
        value = self.camera_data.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return self.camera_id.replace("_", " ").replace("-", " ").title()

    def _control_state(self, control: str) -> dict[str, Any]:
        controls = self.camera_data.get("controls")
        if not isinstance(controls, Mapping):
            return {"value": None, "known": False, "source": "unknown"}
        state = controls.get(control)
        if not isinstance(state, Mapping):
            return {"value": None, "known": False, "source": "unknown"}
        return dict(state)

    async def _async_set_control(
        self, control: str, payload: Mapping[str, Any]
    ) -> None:
        """Send one command and ask the shared coordinator to read it back."""
        try:
            await self.coordinator.api.async_set_control(
                self.camera_id, control, payload
            )
            await self.coordinator.async_request_refresh()
        except InoA9ApiError as error:
            raise HomeAssistantError("Unable to control the INO-A9 camera") from error


def intrusion_payload(state: Mapping[str, Any], enabled: bool) -> dict[str, Any]:
    """Build the complete app payload required by the intrusion command."""
    value = state.get("value") if state.get("known") is True else None
    schedule = value.get("schedule") if isinstance(value, Mapping) else None
    if schedule is None:
        if enabled:
            raise HomeAssistantError(
                "Set an intrusion schedule before enabling intrusion detection"
            )
        schedule = {"days": list(range(7)), "start": "00:00", "end": "23:59"}
    return {"enabled": enabled, "schedule": _validated_schedule(schedule)}


def _validated_schedule(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HomeAssistantError("The camera has no valid intrusion schedule")
    days = value.get("days")
    start = value.get("start")
    end = value.get("end")
    if (
        not isinstance(days, (list, tuple))
        or not days
        or any(type(day) is not int or not 0 <= day <= 6 for day in days)
        or list(days) != sorted(set(days))
        or not isinstance(start, str)
        or not isinstance(end, str)
    ):
        raise HomeAssistantError("The camera has no valid intrusion schedule")
    try:
        start_time = time.fromisoformat(start)
        end_time = time.fromisoformat(end)
    except ValueError as error:
        raise HomeAssistantError(
            "The camera has no valid intrusion schedule"
        ) from error
    if start_time > end_time:
        raise HomeAssistantError("The camera has no valid intrusion schedule")
    return {"days": list(days), "start": start, "end": end}


def platform_entities(coordinator: InoA9Coordinator) -> list[dict[str, Any]]:
    """Return current camera documents for platform setup helpers."""
    return [
        value
        for value in coordinator.data.values()
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    ]
