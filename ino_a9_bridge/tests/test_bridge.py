from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from http.client import HTTPConnection
import json
from pathlib import Path
import threading

from wificam_bridge.bridge import (
    BridgeHandler,
    BridgeHTTPServer,
    CameraState,
    PREVIEW_INTERVAL_SECONDS,
    build_parser,
    parse_config,
)
from wificam_bridge.control_api import ControlStateStore


class _ControlCamera:
    def status(self) -> dict[str, object]:
        return {"connected": True, "has_frame": False, "has_audio": False, "error": None}

    def set_status_led(self, enabled: bool) -> None:
        self.led = enabled

    def get_night_vision(self) -> str:
        return "automatic"

    def get_flip(self) -> str:
        return "upright"


def _handler(path: str) -> tuple[BridgeHandler, CameraState]:
    state = CameraState()
    handler = object.__new__(BridgeHandler)
    handler.path = path
    handler.server = SimpleNamespace(states={"camera1": state})
    handler._snapshot = Mock()
    handler._stream = Mock()
    handler._audio = Mock()
    handler.send_error = Mock()
    return handler, state


def test_preview_endpoint_uses_one_frame_per_second_limit() -> None:
    handler, state = _handler("/camera1/preview.mjpeg")

    handler.do_GET()

    handler._stream.assert_called_once_with(
        state,
        minimum_interval=PREVIEW_INTERVAL_SECONDS,
    )
    handler.send_error.assert_not_called()


def test_full_stream_endpoint_has_no_frame_rate_limit() -> None:
    handler, state = _handler("/camera1/stream.mjpeg")

    handler.do_GET()

    handler._stream.assert_called_once_with(state)
    handler.send_error.assert_not_called()


def test_audio_endpoint_uses_camera_state() -> None:
    handler, state = _handler("/camera1/audio.alaw")

    handler.do_GET()

    handler._audio.assert_called_once_with(state)
    handler.send_error.assert_not_called()


def test_camera_state_stays_available_during_a_recent_reconnect() -> None:
    state = CameraState()
    state.publish_audio(b"audio")
    state.set_connected(False, "ConnectionResetError: peer reset")

    status = state.status()

    assert status["connected"] is True
    assert status["error"] == "ConnectionResetError: peer reset"


def test_parse_config_rejects_duplicate_camera_names() -> None:
    config = {
        "cameras": [
            {
                "name": "same",
                "host": "192.0.2.10",
                "bootstrap_prefix": "LLM_",
                "user": "user",
                "lan_password": "password",
            },
            {
                "name": "same",
                "host": "192.0.2.11",
                "bootstrap_prefix": "LLM_",
                "user": "user",
                "lan_password": "password",
            },
        ]
    }

    try:
        parse_config(config)
    except ValueError as error:
        assert "duplicate camera name" in str(error)
    else:
        raise AssertionError("duplicate camera names must be rejected")


def test_bridge_parser_accepts_supervisor_log_level() -> None:
    args = build_parser().parse_args(["--config", "config.json", "--log-level", "warning"])

    assert args.log_level == "warning"


def test_bridge_server_exposes_authenticated_control_api_without_affecting_media_paths(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "control_token"
    token_path.write_text("token\n", encoding="utf-8")
    states = {"front": CameraState()}
    states["front"].publish(b"\xff\xd8frame\xff\xd9")
    server = BridgeHTTPServer(
        ("127.0.0.1", 0),
        states,
        controls={"front": _ControlCamera()},
        control_token=token_path,
        control_state=ControlStateStore(tmp_path / "control_state.json", ["front"]),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        connection.request(
            "PUT",
            "/api/v1/cameras/front/controls/led",
            body=json.dumps({"value": True}),
            headers={
                "Authorization": "Bearer token",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {
            "id": "front",
            "controls": {"led": {"value": True, "known": True, "source": "persisted"}},
        }
        connection.request("GET", "/front/snapshot.jpg")
        media_response = connection.getresponse()
        assert media_response.status == 200
        media_response.read()
        connection.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
