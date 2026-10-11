"""Button platform for INO-A9 camera controls."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InoA9ApiError
from .coordinator import InoA9Coordinator
from .entity import InoA9Entity, platform_entities


class InoA9RebootButton(InoA9Entity, ButtonEntity):
    """Reboot one physical INO-A9 camera."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(
        self, coordinator: InoA9Coordinator, entry: ConfigEntry, camera_id: str
    ) -> None:
        InoA9Entity.__init__(self, coordinator, entry, camera_id, "reboot", "Reboot")

    async def async_press(self) -> None:
        """Request a reboot through the authenticated app API."""
        try:
            await self.coordinator.api.async_reboot(self.camera_id)
        except InoA9ApiError as error:
            raise HomeAssistantError("Unable to reboot the INO-A9 camera") from error


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a reboot button for every configured camera."""
    del hass
    coordinator: InoA9Coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            InoA9RebootButton(coordinator, entry, camera["id"])
            for camera in platform_entities(coordinator)
        ]
    )
