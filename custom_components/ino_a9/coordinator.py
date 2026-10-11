"""Coordinator for INO-A9 app camera state."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InoA9Api
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


class InoA9Coordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Poll the app and keep all camera details in one place."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: InoA9Api,
        *,
        config_entry: ConfigEntry | None = None,
        update_interval: timedelta = timedelta(seconds=10),
    ) -> None:
        self.api = api
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_method=self._async_update_data,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch the camera list and details concurrently."""
        try:
            summaries = await self.api.async_list_cameras()
            camera_ids = [summary.get("id") for summary in summaries]
            if any(
                not isinstance(camera_id, str) or not camera_id
                for camera_id in camera_ids
            ):
                raise ValueError("app returned an invalid camera id")
            details = await asyncio.gather(
                *(self.api.async_get_camera(camera_id) for camera_id in camera_ids)
            )
            return {detail["id"]: detail for detail in details}
        except UpdateFailed:
            raise
        except Exception as error:
            raise UpdateFailed("Unable to update INO-A9 cameras") from error
