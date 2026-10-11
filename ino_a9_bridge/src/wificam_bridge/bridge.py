"""Small multi-camera HTTP MJPEG bridge for Home Assistant and browsers."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from .camera import CameraClient, CameraCredentials
from .control_api import ControlAPI, ControlStateStore
from .session import CameraSession, CameraUnavailable


LOGGER = logging.getLogger("wificam_bridge")
BOUNDARY = "ino-a9-frame"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
PREVIEW_INTERVAL_SECONDS = 1.0
RECONNECT_DELAY_SECONDS = 1.0
RECENT_ACTIVITY_GRACE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class CameraSettings:
    name: str
    host: str
    port: int
    credentials: CameraCredentials


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    listen_host: str
    listen_port: int
    cameras: tuple[CameraSettings, ...]


def load_config(path: str | Path) -> BridgeSettings:
    """Load a private JSON configuration file."""
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    return parse_config(raw)


def parse_config(raw: object) -> BridgeSettings:
    """Validate a decoded bridge configuration object."""
    if not isinstance(raw, dict):
        raise ValueError("bridge config must be a JSON object")
    camera_values = raw.get("cameras")
    if not isinstance(camera_values, list) or not camera_values:
        raise ValueError("bridge config must contain a non-empty cameras list")
    cameras: list[CameraSettings] = []
    names: set[str] = set()
    for value in camera_values:
        if not isinstance(value, dict):
            raise ValueError("each camera config must be a JSON object")
        name = _required_string(value, "name")
        if not SAFE_NAME.fullmatch(name):
            raise ValueError(f"invalid camera name {name!r}")
        if name in names:
            raise ValueError(f"duplicate camera name {name!r}")
        names.add(name)
        credentials = CameraCredentials(
            bootstrap_prefix=_required_string(value, "bootstrap_prefix").encode("utf-8"),
            user=_required_string(value, "user"),
            lan_password=_required_string(value, "lan_password"),
        )
        cameras.append(
            CameraSettings(
                name=name,
                host=_required_string(value, "host"),
                port=_port(value.get("port", 20190), "camera port"),
                credentials=credentials,
            )
        )
    return BridgeSettings(
        listen_host=str(raw.get("listen_host", "127.0.0.1")),
        listen_port=_port(raw.get("listen_port", 8080), "listen_port"),
        cameras=tuple(cameras),
    )


class CameraState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.frame: bytes | None = None
        self.frame_id = 0
        self.audio_chunks: deque[tuple[int, bytes]] = deque(maxlen=128)
        self.audio_id = 0
        self.connected = False
        self.last_frame_at: float | None = None
        self.last_audio_at: float | None = None
        self.error: str | None = None

    def set_connected(self, connected: bool, error: str | None = None) -> None:
        with self.condition:
            self.connected = connected
            self.error = error
            self.condition.notify_all()

    def publish(self, frame: bytes) -> None:
        with self.condition:
            self.frame = frame
            self.frame_id += 1
            self.connected = True
            self.error = None
            self.last_frame_at = time.time()
            self.condition.notify_all()

    def publish_audio(self, chunk: bytes) -> None:
        with self.condition:
            self.audio_id += 1
            self.audio_chunks.append((self.audio_id, chunk))
            self.last_audio_at = time.time()
            self.condition.notify_all()

    def wait_for_frame(self, after: int, timeout: float) -> tuple[int, bytes] | None:
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.frame is None or self.frame_id == after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return self.frame_id, self.frame

    def audio_cursor(self) -> int:
        with self.condition:
            return self.audio_id

    def wait_for_audio(
        self,
        after: int,
        timeout: float,
    ) -> list[tuple[int, bytes]] | None:
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.audio_id <= after:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return [
                (item_id, chunk)
                for item_id, chunk in self.audio_chunks
                if item_id > after
            ]

    def status(self) -> dict[str, Any]:
        with self.condition:
            activity_times = [
                timestamp
                for timestamp in (self.last_frame_at, self.last_audio_at)
                if timestamp is not None
            ]
            last_activity_at = max(activity_times, default=None)
            recently_active = (
                last_activity_at is not None
                and time.time() - last_activity_at <= RECENT_ACTIVITY_GRACE_SECONDS
            )
            return {
                "connected": self.connected or recently_active,
                "has_frame": self.frame is not None,
                "has_audio": bool(self.audio_chunks),
                "last_frame_at": self.last_frame_at,
                "last_audio_at": self.last_audio_at,
                "error": self.error,
            }


class CameraWorker(threading.Thread):
    def __init__(
        self,
        settings: CameraSettings,
        state: CameraState,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name=f"camera-{settings.name}", daemon=True)
        self.settings = settings
        self.state = state
        self.stop_event = stop_event
        self._session_lock = threading.Lock()
        self._session: CameraSession | None = None

    def run(self) -> None:
        client = CameraClient(
            self.settings.host,
            self.settings.credentials,
            port=self.settings.port,
        )
        session = client.open_session()
        with self._session_lock:
            self._session = session
        session.start(on_frame=self.state.publish, on_audio=self.state.publish_audio)
        try:
            while not self.stop_event.is_set():
                error = session.error
                if session.connected:
                    self.state.set_connected(True)
                else:
                    message = None if error is None else f"{type(error).__name__}: {error}"
                    self.state.set_connected(False, message)
                self.stop_event.wait(0.1)
        finally:
            session.close()
            with self._session_lock:
                self._session = None

    def status(self) -> dict[str, Any]:
        return self.state.status()

    def set_status_led(self, enabled: bool) -> None:
        self._active_session().set_status_led(enabled)

    def set_night_vision(self, value: str) -> None:
        self._active_session().set_night_vision(value)

    def get_night_vision(self) -> str:
        return self._active_session().get_night_vision()

    def set_flip(self, value: str) -> None:
        self._active_session().set_flip(value)

    def get_flip(self) -> str:
        return self._active_session().get_flip()

    def set_video_quality(self, value: str) -> None:
        self._active_session().set_video_quality(value)

    def set_motion(self, value: str) -> None:
        self._active_session().set_motion(value)

    def set_intrusion(self, enabled: bool, schedule) -> None:
        self._active_session().set_intrusion(enabled, schedule)

    def reboot(self) -> None:
        self._active_session().reboot()

    def _active_session(self) -> CameraSession:
        with self._session_lock:
            session = self._session
        if session is None:
            raise CameraUnavailable("camera worker is stopped")
        return session


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        states: dict[str, CameraState],
        *,
        controls: dict[str, object] | None = None,
        control_token: str | Path | None = None,
        control_state: ControlStateStore | None = None,
    ) -> None:
        super().__init__(address, BridgeHandler)
        self.states = states
        if controls is None and control_token is None and control_state is None:
            self.control_api: ControlAPI | None = None
        elif controls is None or control_token is None or control_state is None:
            raise ValueError("controls, control_token, and control_state must be provided together")
        else:
            self.control_api = ControlAPI(controls, control_token, control_state)


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "INOA9Bridge/0.1"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlsplit(self.path).path
        if getattr(self.server, "control_api", None) is not None and (
            path == "/health" or path.startswith("/api/")
        ):
            self._api()
            return
        if path in ("/", "/health"):
            self._health()
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) != 2 or parts[0] not in self.server.states:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        state = self.server.states[parts[0]]
        if parts[1] == "snapshot.jpg":
            self._snapshot(state)
        elif parts[1] == "stream.mjpeg":
            self._stream(state)
        elif parts[1] == "preview.mjpeg":
            self._stream(state, minimum_interval=PREVIEW_INTERVAL_SECONDS)
        elif parts[1] == "audio.alaw":
            self._audio(state)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._api()

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._api()

    def _api(self) -> None:
        api = self.server.control_api
        if api is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = self.headers.get("Content-Length", "0")
        try:
            raw_body = self.rfile.read(int(length))
        except ValueError:
            raw_body = b""
        result = api.handle(self.command, urlsplit(self.path).path, self.headers, raw_body)
        body = json.dumps(result.body, separators=(",", ":")).encode("utf-8")
        self.send_response(result.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _health(self) -> None:
        body = json.dumps(
            {name: state.status() for name, state in self.server.states.items()},
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _snapshot(self, state: CameraState) -> None:
        value = state.wait_for_frame(-1, 5.0)
        if value is None:
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "camera has no frame")
            return
        _, frame = value
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(frame)

    def _stream(self, state: CameraState, *, minimum_interval: float = 0.0) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        frame_id = -1
        next_frame_at = 0.0
        try:
            while True:
                value = state.wait_for_frame(frame_id, 15.0)
                if value is None:
                    continue
                frame_id, frame = value
                if minimum_interval:
                    now = time.monotonic()
                    if now < next_frame_at:
                        continue
                    next_frame_at = now + minimum_interval
                header = (
                    f"--{BOUNDARY}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode("ascii")
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _audio(self, state: CameraState) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/G711-ALAW; rate=8000; channels=1")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        audio_id = state.audio_cursor()
        try:
            while True:
                chunks = state.wait_for_audio(audio_id, 15.0)
                if chunks is None:
                    continue
                for audio_id, chunk in chunks:
                    self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def log_message(self, message: str, *args: object) -> None:
        LOGGER.info("http %s - %s", self.client_address[0], message % args)


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"camera config field {key!r} must be a non-empty string")
    return result


def _port(value: object, label: str) -> int:
    if not isinstance(value, int) or not (1 <= value <= 65535):
        raise ValueError(f"{label} must be an integer from 1 to 65535")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Expose INO-A9 cameras as local MJPEG")
    parser.add_argument("--config", required=True, help="private bridge JSON configuration")
    parser.add_argument("--control-token", help="private API bearer token file")
    parser.add_argument("--control-state", help="non-secret persistent control state file")
    parser.add_argument(
        "--log-level",
        choices=("debug", "info", "warning", "error"),
        default="info",
        help="bridge log level",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = load_config(args.config)
    stop_event = threading.Event()
    states = {camera.name: CameraState() for camera in settings.cameras}
    workers = [
        CameraWorker(camera, states[camera.name], stop_event)
        for camera in settings.cameras
    ]
    for worker in workers:
        worker.start()
    control_state = None
    if (args.control_token is None) != (args.control_state is None):
        parser.error("--control-token and --control-state must be used together")
    if args.control_token is not None and args.control_state is not None:
        control_state = ControlStateStore(args.control_state, list(states))
    server = BridgeHTTPServer(
        (settings.listen_host, settings.listen_port),
        states,
        controls={worker.settings.name: worker for worker in workers} if control_state else None,
        control_token=args.control_token,
        control_state=control_state,
    )
    LOGGER.info("HTTP bridge listening on %s:%d", settings.listen_host, settings.listen_port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        LOGGER.info("stopping")
    finally:
        stop_event.set()
        server.server_close()
        for worker in workers:
            worker.join(timeout=5.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
