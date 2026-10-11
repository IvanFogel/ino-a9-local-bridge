from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from wificam_bridge.app_runtime import prepare_runtime, register_discovery


def _options(
    *, cameras: list[dict[str, object]], log_level: str = "info"
) -> dict[str, object]:
    return {"log_level": log_level, "cameras": cameras}


def _camera(name: str = "front_door") -> dict[str, object]:
    return {
        "name": name,
        "host": "192.0.2.10",
        "port": 20190,
        "bootstrap_prefix": "LLM_",
        "user": "local-user",
        "lan_password": "private-password",
    }


def test_prepare_runtime_writes_stable_camera_streams_and_token(tmp_path: Path) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(json.dumps(_options(cameras=[_camera()])), encoding="utf-8")

    first = prepare_runtime(options_path, tmp_path / "data")
    second = prepare_runtime(options_path, tmp_path / "data")

    bridge = json.loads(first.bridge_config.read_text(encoding="utf-8"))
    assert bridge["listen_host"] == "0.0.0.0"
    assert bridge["listen_port"] == 8080
    assert bridge["cameras"] == [_camera()]
    go2rtc = first.go2rtc_config.read_text(encoding="utf-8")
    assert "ino_a9_front_door:" in go2rtc
    assert "http://127.0.0.1:8080/front_door/stream.mjpeg" in go2rtc
    assert "http://127.0.0.1:8080/front_door/audio.alaw" in go2rtc
    assert json.loads(first.control_state.read_text(encoding="utf-8")) == {
        "version": 1,
        "cameras": {"front_door": {}},
    }
    assert first.control_token.read_text(encoding="utf-8") == second.control_token.read_text(
        encoding="utf-8"
    )
    assert first.control_token.stat().st_mode & 0o777 == 0o600


def test_prepare_runtime_rejects_duplicate_or_empty_camera_configuration(tmp_path: Path) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(_options(cameras=[_camera("same"), _camera("same")])),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate camera name"):
        prepare_runtime(options_path, tmp_path / "data")

    options_path.write_text(json.dumps(_options(cameras=[])), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty cameras list"):
        prepare_runtime(options_path, tmp_path / "data")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "front/door"}, "invalid camera name"),
        ({"host": ""}, "field 'host'"),
        ({"bootstrap_prefix": ""}, "field 'bootstrap_prefix'"),
        ({"user": ""}, "field 'user'"),
        ({"lan_password": ""}, "field 'lan_password'"),
        ({"port": 0}, "camera port"),
        ({"port": 65536}, "camera port"),
        ({"port": "20190"}, "camera port"),
    ],
)
def test_prepare_runtime_rejects_unsafe_or_incomplete_camera_fields(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    camera = _camera()
    camera.update(changes)
    options_path = _write_options(tmp_path, _options(cameras=[camera]))

    with pytest.raises(ValueError, match=message):
        prepare_runtime(options_path, tmp_path / "data")


def test_prepare_runtime_applies_log_level_to_go2rtc(tmp_path: Path) -> None:
    runtime = prepare_runtime(
        _write_options(tmp_path, _options(cameras=[_camera()], log_level="warning")),
        tmp_path / "data",
    )

    assert "  level: warning\n" in runtime.go2rtc_config.read_text(encoding="utf-8")


def test_register_discovery_publishes_internal_endpoints_and_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = prepare_runtime(
        _write_options(tmp_path, _options(cameras=[_camera()])), tmp_path / "data"
    )
    received: list[tuple[str, dict[str, object]]] = []
    received_authorization: list[str | None] = []

    class SupervisorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received_authorization.append(self.headers.get("Authorization"))
            self._send({"data": {"hostname": "local_ino_a9_bridge"}})

        def do_POST(self) -> None:  # noqa: N802
            received_authorization.append(self.headers.get("Authorization"))
            length = int(self.headers["Content-Length"])
            received.append((self.path, json.loads(self.rfile.read(length))))
            self._send({"data": {"uuid": "test"}})

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _send(self, payload: dict[str, object]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), SupervisorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-supervisor-token")
    try:
        register_discovery(runtime, f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        thread.join()

    assert received == [
        (
            "/discovery",
            {
                "service": "ino_a9",
                "config": {
                    "host": "local-ino-a9-bridge",
                    "http_port": 8080,
                    "rtsp_port": 8554,
                    "token": runtime.control_token.read_text(encoding="utf-8").strip(),
                },
            },
        )
    ]
    assert received_authorization == [
        "Bearer test-supervisor-token",
        "Bearer test-supervisor-token",
    ]


def _write_options(path: Path, options: dict[str, object]) -> Path:
    options_path = path / "options.json"
    options_path.write_text(json.dumps(options), encoding="utf-8")
    return options_path
