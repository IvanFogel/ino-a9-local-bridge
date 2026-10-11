"""Camera connection diagnostics that remain readable while a camera is offline."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .coordinator import InoA9Coordinator
from .entity import InoA9Entity, platform_entities

MAX_ERRORS = 10


def _safe_error(value: object) -> str | None:
    """Keep diagnostic text bounded and omit credential-bearing messages."""
    if not isinstance(value, str) or not value.strip():
        return None
    if any(
        word in value.lower() for word in ("password", "token", "authorization", "://")
    ):
        return "Camera connection failed (sensitive details omitted)"
    return " ".join(value.split())[:512]


class InoA9ConnectionDiagnostics(InoA9Entity, RestoreEntity, SensorEntity):
    """Expose current connectivity and the ten most recent observed errors."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["connected", "disconnected"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:camera-alert"

    def __init__(
        self, coordinator: InoA9Coordinator, entry: ConfigEntry, camera_id: str
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            camera_id,
            "connection_diagnostics",
            "Connection diagnostics",
        )
        self._error_log: list[dict[str, str]] = []
        self._last_logged_error: str | None = None

    @property
    def available(self) -> bool:
        """An offline camera must not hide its own diagnostic information."""
        return (
            self.coordinator.last_update_success
            and self.camera_id in self.coordinator.data
        )

    @property
    def native_value(self) -> str:
        return (
            "connected" if self.camera_data.get("connected") is True else "disconnected"
        )

    @property
    def current_error(self) -> str | None:
        if self.native_value == "connected":
            return None
        media = self.camera_data.get("media", {})
        error = _safe_error(media.get("error")) if isinstance(media, dict) else None
        return error or "Camera disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "error": self.current_error,
            "error_log": [dict(row) for row in self._error_log],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (previous := await self.async_get_last_state()) is not None:
            self._restore_errors(previous)
        self._record_error()
        self.async_write_ha_state()

    def _restore_errors(self, previous: State) -> None:
        rows = previous.attributes.get("error_log", [])
        if isinstance(rows, list):
            for row in rows[-MAX_ERRORS:]:
                if not isinstance(row, dict):
                    continue
                timestamp = row.get("timestamp")
                message = _safe_error(row.get("message"))
                if (
                    isinstance(timestamp, str)
                    and dt_util.parse_datetime(timestamp)
                    and message
                ):
                    self._error_log.append({"timestamp": timestamp, "message": message})
        self._last_logged_error = _safe_error(previous.attributes.get("error"))

    @callback
    def _record_error(self) -> None:
        error = self.current_error
        if error and error != self._last_logged_error:
            self._error_log.append(
                {"timestamp": dt_util.utcnow().isoformat(), "message": error}
            )
            self._error_log = self._error_log[-MAX_ERRORS:]
        self._last_logged_error = error

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.last_update_success:
            self._record_error()
        super()._handle_coordinator_update()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Use the existing coordinator, without additional camera connections."""
    del hass
    coordinator: InoA9Coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            InoA9ConnectionDiagnostics(coordinator, entry, camera["id"])
            for camera in platform_entities(coordinator)
        ]
    )
