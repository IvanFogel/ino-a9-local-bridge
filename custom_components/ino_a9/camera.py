"""Camera platform for INO-A9 Local Bridge."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InoA9ApiError
from .coordinator import InoA9Coordinator
from .entity import InoA9Entity, platform_entities


class InoA9Camera(InoA9Entity, Camera):
    """One camera exposed by the app's local RTSP and snapshot endpoints."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "INO-A9"
    _attr_model = "Local Bridge Camera"

    def __init__(
        self, coordinator: InoA9Coordinator, entry: ConfigEntry, camera_id: str
    ) -> None:
        InoA9Entity.__init__(
            self,
            coordinator,
            entry,
            camera_id,
            "camera",
            "Camera",
        )
        Camera.__init__(self)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Fetch a JPEG snapshot from the authenticated app endpoint."""
        del width, height
        try:
            return await self.coordinator.api.async_get_snapshot(self.camera_id)
        except InoA9ApiError as error:
            raise HomeAssistantError(
                "Unable to fetch the INO-A9 camera image"
            ) from error

    async def stream_source(self) -> str | None:
        """Return the app-owned RTSP URL, including the audio track."""
        return self.coordinator.api.rtsp_url(self.camera_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up all cameras returned by the initial coordinator refresh."""
    del hass
    coordinator: InoA9Coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            InoA9Camera(coordinator, entry, camera["id"])
            for camera in platform_entities(coordinator)
        ]
    )
