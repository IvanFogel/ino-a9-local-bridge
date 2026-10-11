"""Authenticated Home Assistant control API for shared INO-A9 sessions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from .camera import CameraError
from .commands import FLIP_VALUES, MOTION_VALUES, NIGHT_VALUES, VIDEO_QUALITY_VALUES
from .controls import IntrusionSchedule
from .session import CameraUnavailable


PERSISTED_CONTROLS = ("led", "night_vision", "flip", "video_quality", "motion", "intrusion")
LOGGER = logging.getLogger("wificam_bridge.control_api")


@dataclass(frozen=True, slots=True)
class APIResponse:
    status: HTTPStatus
    body: dict[str, object]


class InvalidRequest(ValueError):
    pass


def _validated_control_value(control: str, value: object) -> object:
    if control == "led":
        if not isinstance(value, bool):
            raise InvalidRequest
        return value
    enum_values = {
        "night_vision": NIGHT_VALUES,
        "flip": FLIP_VALUES,
        "video_quality": VIDEO_QUALITY_VALUES,
        "motion": MOTION_VALUES,
    }
    if control in enum_values:
        if not isinstance(value, str) or value not in enum_values[control]:
            raise InvalidRequest
        return value
    if control != "intrusion" or not isinstance(value, dict):
        raise InvalidRequest
    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise InvalidRequest
    schedule = _schedule_from_value(value.get("schedule"))
    return {
        "enabled": enabled,
        "schedule": {
            "days": list(schedule.days),
            "start": schedule.start.strftime("%H:%M"),
            "end": schedule.end.strftime("%H:%M"),
        },
    }


def _schedule_from_value(value: object) -> IntrusionSchedule:
    if not isinstance(value, dict):
        raise InvalidRequest
    days = value.get("days")
    if not isinstance(days, list):
        raise InvalidRequest
    try:
        return IntrusionSchedule(
            days=tuple(days),
            start=_clock_from_value(value.get("start")),
            end=_clock_from_value(value.get("end")),
        )
    except (TypeError, ValueError) as error:
        raise InvalidRequest from error


def _clock_from_value(value: object):
    if not isinstance(value, str) or len(value) != 5:
        raise InvalidRequest
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as error:
        raise InvalidRequest from error


class ControlStateStore:
    """Atomic, non-secret state retained between app restarts."""

    def __init__(self, path: str | Path, camera_ids: list[str]) -> None:
        self.path = Path(path)
        self._lock = Lock()
        existing: dict[str, object] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("cameras"), dict):
                existing = raw["cameras"]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        self._state: dict[str, dict[str, object]] = {}
        for camera_id in camera_ids:
            camera_values = existing.get(camera_id, {})
            if not isinstance(camera_values, dict):
                camera_values = {}
            retained: dict[str, object] = {}
            for control in PERSISTED_CONTROLS:
                if control not in camera_values:
                    continue
                try:
                    retained[control] = _validated_control_value(
                        control, camera_values[control]
                    )
                except InvalidRequest:
                    continue
            self._state[camera_id] = retained
        self._write()

    def values(self, camera_id: str) -> dict[str, object]:
        with self._lock:
            return dict(self._state[camera_id])

    def set(self, camera_id: str, control: str, value: object) -> None:
        with self._lock:
            self._state[camera_id][control] = _validated_control_value(control, value)
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "cameras": self._state}
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", delete=False
        ) as temporary:
            json.dump(data, temporary, separators=(",", ":"))
            temporary.write("\n")
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o600)
            temporary_path = Path(temporary.name)
        temporary_path.replace(self.path)


class ControlAPI:
    """Route validation and camera-control behavior, independent of HTTP I/O."""

    def __init__(self, cameras: dict[str, object], token_path: str | Path, state: ControlStateStore) -> None:
        self.cameras = cameras
        self._token_path = Path(token_path)
        self.state = state

    def handle(self, method: str, path: str, headers, raw_body: bytes) -> APIResponse:
        if method == "GET" and path == "/health":
            return APIResponse(HTTPStatus.OK, {"status": "ok"})
        if not self._authorized(headers.get("Authorization")):
            return self._error(HTTPStatus.UNAUTHORIZED, "unauthorized")
        parts = [part for part in path.split("/") if part]
        if parts == ["api", "v1", "cameras"] and method == "GET":
            return APIResponse(
                HTTPStatus.OK,
                {
                    "cameras": [
                        {"id": camera_id, "connected": bool(camera.status().get("connected"))}
                        for camera_id, camera in self.cameras.items()
                    ]
                },
            )
        if len(parts) < 4 or parts[:3] != ["api", "v1", "cameras"]:
            return self._error(HTTPStatus.NOT_FOUND, "not_found")
        camera_id = parts[3]
        camera = self.cameras.get(camera_id)
        if camera is None:
            return self._error(HTTPStatus.NOT_FOUND, "not_found")
        try:
            if method == "GET" and len(parts) == 4:
                return APIResponse(HTTPStatus.OK, self._camera_detail(camera_id, camera))
            if method == "PUT" and len(parts) == 6 and parts[4] == "controls":
                return APIResponse(
                    HTTPStatus.OK,
                    self._update_control(camera_id, camera, parts[5], self._json_object(raw_body)),
                )
            if method == "POST" and parts[4:] == ["reboot"]:
                camera.reboot()
                return APIResponse(HTTPStatus.OK, {"id": camera_id, "rebooting": True})
        except InvalidRequest:
            return self._error(HTTPStatus.BAD_REQUEST, "invalid_request")
        except LookupError:
            return self._error(HTTPStatus.NOT_FOUND, "not_found")
        except TimeoutError:
            return self._error(HTTPStatus.GATEWAY_TIMEOUT, "camera_timeout")
        except CameraUnavailable:
            return self._error(HTTPStatus.SERVICE_UNAVAILABLE, "camera_unavailable")
        except CameraError:
            return self._error(HTTPStatus.BAD_GATEWAY, "camera_error")
        return self._error(HTTPStatus.NOT_FOUND, "not_found")

    def _camera_detail(self, camera_id: str, camera) -> dict[str, object]:
        status = camera.status()
        connected = bool(status.get("connected"))
        controls = self._control_values(camera_id)
        if connected and status.get("error") is None:
            controls["night_vision"] = self._safe_readback(
                camera_id,
                "night_vision",
                camera.get_night_vision,
                controls["night_vision"],
            )
            controls["flip"] = self._safe_readback(
                camera_id,
                "flip",
                camera.get_flip,
                controls["flip"],
            )
        media = {key: value for key, value in status.items() if key != "connected"}
        return {"id": camera_id, "connected": connected, "media": media, "controls": controls}

    @staticmethod
    def _safe_readback(
        camera_id: str,
        control: str,
        getter: Callable[[], object],
        fallback: dict[str, object],
    ) -> dict[str, object]:
        try:
            return ControlAPI._known(getter(), "readback")
        except (TimeoutError, CameraError) as error:
            LOGGER.warning(
                "camera %s %s readback failed: %s",
                camera_id,
                control,
                f"{type(error).__name__}: {error}",
            )
            return fallback

    def _update_control(self, camera_id: str, camera, control: str, body: dict[str, object]) -> dict[str, object]:
        if control == "led":
            value = self._boolean(body, "value")
            camera.set_status_led(value)
        elif control == "night_vision":
            value = self._enum(body, "value", NIGHT_VALUES)
            camera.set_night_vision(value)
        elif control == "flip":
            value = self._enum(body, "value", FLIP_VALUES)
            camera.set_flip(value)
        elif control == "video_quality":
            value = self._enum(body, "value", VIDEO_QUALITY_VALUES)
            camera.set_video_quality(value)
        elif control == "motion":
            value = self._enum(body, "value", MOTION_VALUES)
            camera.set_motion(value)
        elif control == "intrusion":
            enabled = self._boolean(body, "enabled")
            schedule = self._schedule(body.get("schedule"))
            camera.set_intrusion(enabled, schedule)
            value = {
                "enabled": enabled,
                "schedule": {
                    "days": list(schedule.days),
                    "start": schedule.start.strftime("%H:%M"),
                    "end": schedule.end.strftime("%H:%M"),
                },
            }
        else:
            raise LookupError(control)
        self.state.set(camera_id, control, value)
        return {"id": camera_id, "controls": {control: self._known(value, "persisted")}}

    def _control_values(self, camera_id: str) -> dict[str, dict[str, object]]:
        saved = self.state.values(camera_id)
        return {
            control: self._known(saved[control], "persisted")
            if control in saved
            else {"value": None, "known": False, "source": "unknown"}
            for control in PERSISTED_CONTROLS
        }

    def _authorized(self, header: object) -> bool:
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        try:
            token = self._token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return bool(token) and secrets.compare_digest(header[7:], token)

    @staticmethod
    def _known(value: object, source: str) -> dict[str, object]:
        return {"value": value, "known": True, "source": source}

    @staticmethod
    def _error(status: HTTPStatus, code: str) -> APIResponse:
        return APIResponse(status, {"error": {"code": code, "message": "camera operation failed" if code.startswith("camera_") else "request failed"}})

    @staticmethod
    def _json_object(raw_body: bytes) -> dict[str, object]:
        try:
            value = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidRequest from error
        if not isinstance(value, dict):
            raise InvalidRequest
        return value

    @staticmethod
    def _boolean(body: dict[str, object], key: str) -> bool:
        value = body.get(key)
        if not isinstance(value, bool):
            raise InvalidRequest
        return value

    @staticmethod
    def _enum(body: dict[str, object], key: str, values: dict[str, int]) -> str:
        value = body.get(key)
        if not isinstance(value, str) or value not in values:
            raise InvalidRequest
        return value

    @staticmethod
    def _schedule(value: object) -> IntrusionSchedule:
        return _schedule_from_value(value)

    @staticmethod
    def _clock(value: object):
        return _clock_from_value(value)


class ControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], api: ControlAPI) -> None:
        super().__init__(address, ControlHandler)
        self.api = api


class ControlHandler(BaseHTTPRequestHandler):
    server: ControlHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._respond()

    def do_PUT(self) -> None:  # noqa: N802
        self._respond()

    def do_POST(self) -> None:  # noqa: N802
        self._respond()

    def _respond(self) -> None:
        length = self.headers.get("Content-Length", "0")
        try:
            raw_body = self.rfile.read(int(length))
        except ValueError:
            raw_body = b""
        result = self.server.api.handle(self.command, urlsplit(self.path).path, self.headers, raw_body)
        body = json.dumps(result.body, separators=(",", ":")).encode("utf-8")
        self.send_response(result.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return
