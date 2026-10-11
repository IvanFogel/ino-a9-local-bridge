"""Asynchronous client for the INO-A9 Home Assistant app."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_VERSION


class InoA9ApiError(RuntimeError):
    """Raised when the app cannot fulfil an API request."""

    def __init__(self, status: int, message: str = "INO-A9 app request failed") -> None:
        super().__init__(message)
        self.status = status


class InoA9Api:
    """Small authenticated client for the app's versioned API."""

    def __init__(
        self,
        host: str,
        http_port: int,
        rtsp_port: int,
        token: str,
        session: ClientSession,
    ) -> None:
        if not host or not isinstance(host, str):
            raise ValueError("host must be a non-empty string")
        if not isinstance(http_port, int) or not 1 <= http_port <= 65535:
            raise ValueError("http_port must be between 1 and 65535")
        if not isinstance(rtsp_port, int) or not 1 <= rtsp_port <= 65535:
            raise ValueError("rtsp_port must be between 1 and 65535")
        if not token or not isinstance(token, str):
            raise ValueError("token must be a non-empty string")
        self.host = host
        self.http_port = http_port
        self.rtsp_port = rtsp_port
        self._token = token
        self._session = session

    @property
    def base_url(self) -> str:
        """Return the app HTTP base URL."""
        host = (
            f"[{self.host}]"
            if ":" in self.host and not self.host.startswith("[")
            else self.host
        )
        return f"http://{host}:{self.http_port}"

    def rtsp_url(self, camera_id: str) -> str:
        """Return the stable audio-capable RTSP URL for a camera."""
        host = (
            f"[{self.host}]"
            if ":" in self.host and not self.host.startswith("[")
            else self.host
        )
        return f"rtsp://{host}:{self.rtsp_port}/ino_a9_{camera_id}"

    async def async_list_cameras(self) -> list[dict[str, Any]]:
        """Return the app's configured camera summaries."""
        payload = await self._request_json("GET", f"/api/{API_VERSION}/cameras")
        cameras = payload.get("cameras")
        if not isinstance(cameras, list) or any(
            not isinstance(item, dict) for item in cameras
        ):
            raise InoA9ApiError(502, "invalid camera list")
        return cameras

    async def async_get_camera(self, camera_id: str) -> dict[str, Any]:
        """Return one camera detail document."""
        payload = await self._request_json(
            "GET", f"/api/{API_VERSION}/cameras/{_path_part(camera_id)}"
        )
        if payload.get("id") != camera_id:
            raise InoA9ApiError(502, "invalid camera detail")
        return payload

    async def async_set_control(
        self, camera_id: str, control: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Set one camera control and return the app response."""
        return await self._request_json(
            "PUT",
            f"/api/{API_VERSION}/cameras/{_path_part(camera_id)}/controls/{_path_part(control)}",
            json_payload=dict(payload),
        )

    async def async_reboot(self, camera_id: str) -> dict[str, Any]:
        """Request a camera reboot."""
        return await self._request_json(
            "POST", f"/api/{API_VERSION}/cameras/{_path_part(camera_id)}/reboot"
        )

    async def async_get_snapshot(self, camera_id: str) -> bytes:
        """Fetch one JPEG snapshot through the authenticated app endpoint."""
        return await self._request_bytes(
            "GET", f"/{_path_part(camera_id)}/snapshot.jpg"
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._request(method, path, json_payload=json_payload) as response:
            try:
                value = await response.json()
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise InoA9ApiError(502, "invalid app response") from error
        if not isinstance(value, dict):
            raise InoA9ApiError(502, "invalid app response")
        return value

    async def _request_bytes(self, method: str, path: str) -> bytes:
        async with self._request(method, path) as response:
            return await response.read()

    @asynccontextmanager
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ):
        headers = {"Authorization": f"Bearer {self._token}"}
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with self._session.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=json_payload,
            ) as response:
                if response.status >= 400:
                    await response.read()
                    raise InoA9ApiError(response.status)
                yield response
        except InoA9ApiError:
            raise
        except (TimeoutError, ClientError, OSError) as error:
            raise InoA9ApiError(503) from error


def _path_part(value: str) -> str:
    """Validate a path component without allowing URL traversal."""
    if (
        not isinstance(value, str)
        or not value
        or "/" in value
        or "?" in value
        or "#" in value
    ):
        raise ValueError("invalid path component")
    return value
