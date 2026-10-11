"""Switch platform for INO-A9 camera controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONTROL_INTRUSION, CONTROL_LED
from .coordinator import InoA9Coordinator
from .entity import InoA9Entity, intrusion_payload, platform_entities


class InoA9Switch(InoA9Entity, SwitchEntity):
    """LED or intrusion-detection switch for one camera."""

    def __init__(
        self,
        coordinator: InoA9Coordinator,
        entry: ConfigEntry,
        camera_id: str,
        control: str,
    ) -> None:
        if control not in (CONTROL_LED, CONTROL_INTRUSION):
            raise ValueError("unsupported INO-A9 switch control")
        label = "Status LED" if control == CONTROL_LED else "Intrusion detection"
        InoA9Entity.__init__(self, coordinator, entry, camera_id, control, label)
        self.control = control

    @property
    def is_on(self) -> bool | None:
        """Return the known switch state, or None while it is unknown."""
        state = self._control_state(self.control)
        if state.get("known") is not True:
            return None
        value = state.get("value")
        if self.control == CONTROL_INTRUSION and isinstance(value, dict):
            value = value.get("enabled")
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        del kwargs
        payload = {"value": True}
        if self.control == CONTROL_INTRUSION:
            payload = intrusion_payload(self._control_state(self.control), enabled=True)
        await self._async_set_control(self.control, payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        payload = {"value": False}
        if self.control == CONTROL_INTRUSION:
            payload = intrusion_payload(
                self._control_state(self.control), enabled=False
            )
        await self._async_set_control(self.control, payload)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up LED and intrusion switches for every configured camera."""
    del hass
    coordinator: InoA9Coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            InoA9Switch(coordinator, entry, camera["id"], control)
            for camera in platform_entities(coordinator)
            for control in (CONTROL_LED, CONTROL_INTRUSION)
        ]
    )
