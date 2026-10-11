from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import threading

import pytest

from wificam_bridge.camera import CameraError
from wificam_bridge.control_api import ControlAPI, ControlHTTPServer, ControlStateStore
from wificam_bridge.session import CameraUnavailable


class _Camera:
    def __init__(self) -> None:
        self.connected = True
        self.calls: list[tuple[str, object]] = []
        self.failure: Exception | None = None

    def status(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "has_frame": True,
            "has_audio": True,
            "last_frame_at": 1.0,
            "last_audio_at": 2.0,
            "error": None,
        }

    def _call(self, name: str, value: object = None) -> None:
        if self.failure is not None:
            raise self.failure
        self.calls.append((name, value))

    def set_status_led(self, value: bool) -> None:
        self._call("led", value)

    def set_night_vision(self, value: str) -> None:
        self._call("night", value)

    def get_night_vision(self) -> str:
        self._call("night_get")
        return "automatic"

    def set_flip(self, value: str) -> None:
        self._call("flip", value)

    def get_flip(self) -> str:
        self._call("flip_get")
        return "rotate_180"

    def set_video_quality(self, value: str) -> None:
        self._call("video_quality", value)

    def set_motion(self, value: str) -> None:
        self._call("motion", value)

    def set_intrusion(self, enabled: bool, schedule) -> None:
        self._call("intrusion", (enabled, schedule))

    def reboot(self) -> None:
        self._call("reboot")


@pytest.fixture
def api(tmp_path: Path):
    token_path = tmp_path / "control_token"
    token_path.write_text("test-token\n", encoding="utf-8")
    camera = _Camera()
    state = ControlStateStore(tmp_path / "control_state.json", ["front"])
    server = ControlHTTPServer(("127.0.0.1", 0), ControlAPI({"front": camera}, token_path, state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, camera, state
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_health_is_public_but_camera_api_requires_bearer_token(api) -> None:
    server, _camera, _state = api

    health_status, health = _request(server, "GET", "/health")
    denied_status, denied = _request(server, "GET", "/api/v1/cameras")
    status, body = _request(server, "GET", "/api/v1/cameras", token="test-token")

    assert health_status == 200
    assert health["status"] == "ok"
    assert denied_status == 401
    assert denied["error"]["code"] == "unauthorized"
    assert status == 200
    assert body == {"cameras": [{"id": "front", "connected": True}]}


def test_control_update_persists_nonsecret_value_and_camera_readback_wins(api) -> None:
    server, camera, state = api

    status, updated = _request(
        server,
        "PUT",
        "/api/v1/cameras/front/controls/night_vision",
        {"value": "enabled"},
        token="test-token",
    )
    detail_status, detail = _request(server, "GET", "/api/v1/cameras/front", token="test-token")

    assert status == 200
    assert updated["controls"]["night_vision"] == {
        "value": "enabled", "known": True, "source": "persisted"
    }
    assert detail_status == 200
    assert detail["media"]["has_frame"] is True
    assert detail["controls"]["night_vision"] == {
        "value": "automatic", "known": True, "source": "readback"
    }
    assert detail["controls"]["flip"] == {
        "value": "rotate_180", "known": True, "source": "readback"
    }
    saved = json.loads(state.path.read_text(encoding="utf-8"))
    assert saved == {"version": 1, "cameras": {"front": {"night_vision": "enabled"}}}
    assert camera.calls == [("night", "enabled"), ("night_get", None), ("flip_get", None)]


def test_detail_keeps_camera_available_when_control_readback_fails(api) -> None:
    server, camera, state = api
    state.set("front", "night_vision", "enabled")
    camera.failure = CameraError("rejected")

    status, detail = _request(
        server,
        "GET",
        "/api/v1/cameras/front",
        token="test-token",
    )

    assert status == 200
    assert detail["connected"] is True
    assert detail["controls"]["night_vision"] == {
        "value": "enabled", "known": True, "source": "persisted"
    }
    assert detail["controls"]["flip"] == {
        "value": None, "known": False, "source": "unknown"
    }


def test_state_store_discards_unknown_preexisting_values(tmp_path: Path) -> None:
    path = tmp_path / "control_state.json"
    path.write_text(
        json.dumps({"version": 1, "cameras": {"front": {"led": True, "token": "secret"}}}),
        encoding="utf-8",
    )

    ControlStateStore(path, ["front"])

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "cameras": {"front": {"led": True}},
    }


def test_state_store_discards_invalid_allowed_values_before_api_returns_state(tmp_path: Path) -> None:
    path = tmp_path / "control_state.json"
    token_path = tmp_path / "control_token"
    token_path.write_text("test-token\n", encoding="utf-8")
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "cameras": {
                    "front": {
                        "led": "secret-led-value",
                        "night_vision": "secret-night-value",
                        "flip": "upside-down",
                        "video_quality": "hd",
                        "motion": ["secret-motion-value"],
                        "intrusion": {
                            "enabled": True,
                            "schedule": {"days": [0, 2], "start": "08:00", "end": "17:30"},
                            "secret": "secret-intrusion-value",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    camera = _Camera()
    camera.connected = False
    store = ControlStateStore(path, ["front"])

    response = ControlAPI({"front": camera}, token_path, store).handle(
        "GET",
        "/api/v1/cameras/front",
        {"Authorization": "Bearer test-token"},
        b"",
    )

    assert response.status == 200
    assert response.body["controls"] == {
        "led": {"value": None, "known": False, "source": "unknown"},
        "night_vision": {"value": None, "known": False, "source": "unknown"},
        "flip": {"value": None, "known": False, "source": "unknown"},
        "video_quality": {"value": "hd", "known": True, "source": "persisted"},
        "motion": {"value": None, "known": False, "source": "unknown"},
        "intrusion": {
            "value": {
                "enabled": True,
                "schedule": {"days": [0, 2], "start": "08:00", "end": "17:30"},
            },
            "known": True,
            "source": "persisted",
        },
    }
    assert "secret" not in json.dumps(response.body)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "cameras": {
            "front": {
                "video_quality": "hd",
                "intrusion": {
                    "enabled": True,
                    "schedule": {"days": [0, 2], "start": "08:00", "end": "17:30"},
                },
            }
        },
    }


@pytest.mark.parametrize(
    ("method", "path", "payload", "expected_status", "code"),
    [
        ("PUT", "/api/v1/cameras/front/controls/motion", {"value": "maximum"}, 400, "invalid_request"),
        ("PUT", "/api/v1/cameras/front/controls/intrusion", {"enabled": True, "schedule": {"days": [0], "start": "20:00", "end": "08:00"}}, 400, "invalid_request"),
        ("PUT", "/api/v1/cameras/missing/controls/led", {"value": True}, 404, "not_found"),
        ("PUT", "/api/v1/cameras/front/controls/unknown", {"value": True}, 404, "not_found"),
    ],
)
def test_api_rejects_invalid_payloads_and_unknown_resources(api, method, path, payload, expected_status, code) -> None:
    server, _camera, _state = api

    status, body = _request(server, method, path, payload, token="test-token")

    assert status == expected_status
    assert body["error"]["code"] == code


@pytest.mark.parametrize(
    ("failure", "expected_status", "code"),
    [
        (TimeoutError("slow"), 504, "camera_timeout"),
        (CameraUnavailable("reconnecting"), 503, "camera_unavailable"),
        (CameraError("rejected"), 502, "camera_error"),
    ],
)
def test_api_translates_camera_failures_without_exposing_details(api, failure, expected_status, code) -> None:
    server, camera, _state = api
    camera.failure = failure

    status, body = _request(
        server,
        "POST",
        "/api/v1/cameras/front/reboot",
        token="test-token",
    )

    assert status == expected_status
    assert body == {"error": {"code": code, "message": "camera operation failed"}}


def _request(server, method: str, path: str, payload=None, *, token: str | None = None):
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Length": str(len(body))}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    value = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, value
