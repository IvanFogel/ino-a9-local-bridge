"""Select platform for INO-A9 camera controls."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONTROL_FLIP,
    CONTROL_MOTION,
    CONTROL_NIGHT_VISION,
    CONTROL_VIDEO_QUALITY,
    FLIP_OPTIONS,
    MOTION_OPTIONS,
    NIGHT_VISION_OPTIONS,
    VIDEO_QUALITY_OPTIONS,
)
from .coordinator import InoA9Coordinator
from .entity import InoA9Entity, platform_entities

CONTROL_OPTIONS: dict[str, tuple[str, ...]] = {
    CONTROL_NIGHT_VISION: NIGHT_VISION_OPTIONS,
    CONTROL_FLIP: FLIP_OPTIONS,
    CONTROL_VIDEO_QUALITY: VIDEO_QUALITY_OPTIONS,
    CONTROL_MOTION: MOTION_OPTIONS,
}


CONTROL_LABELS = {
    CONTROL_NIGHT_VISION: "Night vision",
    CONTROL_FLIP: "Image orientation",
    CONTROL_VIDEO_QUALITY: "Video quality",
    CONTROL_MOTION: "Motion sensitivity",
}


class InoA9Select(InoA9Entity, SelectEntity):
    """Enum-valued camera control exposed as a Home Assistant select."""

    def __init__(
        self,
        coordinator: InoA9Coordinator,
        entry: ConfigEntry,
        camera_id: str,
        control: str,
    ) -> None:
        if control not in CONTROL_OPTIONS:
            raise ValueError("unsupported INO-A9 select control")
        InoA9Entity.__init__(
            self,
            coordinator,
            entry,
            camera_id,
            control,
            CONTROL_LABELS[control],
        )
        self.control = control
        self._attr_options = list(CONTROL_OPTIONS[control])

    @property
    def current_option(self) -> str | None:
        """Return the read-back option when it is known and valid."""
        state = self._control_state(self.control)
        value = state.get("value")
        if state.get("known") is True and value in self.options:
            return value
        return None

    async def async_select_option(self, option: str) -> None:
        """Set an enum control through the app."""
        self._valid_option_or_raise(option)
        await self._async_set_control(self.control, {"value": option})


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up all enum controls for every configured camera."""
    del hass
    coordinator: InoA9Coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            InoA9Select(coordinator, entry, camera["id"], control)
            for camera in platform_entities(coordinator)
            for control in CONTROL_OPTIONS
        ]
    )
