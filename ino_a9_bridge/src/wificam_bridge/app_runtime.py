"""Home Assistant app runtime configuration and discovery helpers.

This module deliberately prepares configuration only.  It does not implement a
second camera bridge: the supervised bridge process remains ``bridge.main``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any
from urllib.request import Request, urlopen

from .bridge import parse_config


LOGGER = logging.getLogger("wificam_bridge.app_runtime")
CONTROL_TOKEN_FILENAME = "control_token"
CONTROL_STATE_FILENAME = "control_state.json"
BRIDGE_CONFIG_FILENAME = "bridge.json"
GO2RTC_CONFIG_FILENAME = "go2rtc.yaml"
DISCOVERY_SERVICE = "ino_a9"
LOG_LEVELS = {"debug", "info", "warning", "error"}


@dataclass(frozen=True, slots=True)
class RuntimeFiles:
    bridge_config: Path
    go2rtc_config: Path
    control_state: Path
    control_token: Path


def prepare_runtime(options_path: str | Path, data_dir: str | Path) -> RuntimeFiles:
    """Validate Supervisor options and write private, app-owned runtime files."""
    raw = json.loads(Path(options_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("app options must be a JSON object")
    log_level = raw.get("log_level", "info")
    if not isinstance(log_level, str) or log_level not in LOG_LEVELS:
        raise ValueError("log_level must be debug, info, warning, or error")
    cameras = raw.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        raise ValueError("app options must contain a non-empty cameras list")

    bridge_raw = {
        "listen_host": "0.0.0.0",
        "listen_port": 8080,
        "cameras": cameras,
    }
    settings = parse_config(bridge_raw)
    runtime_dir = Path(data_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    bridge_config = runtime_dir / BRIDGE_CONFIG_FILENAME
    go2rtc_config = runtime_dir / GO2RTC_CONFIG_FILENAME
    control_state = runtime_dir / CONTROL_STATE_FILENAME
    control_token = runtime_dir / CONTROL_TOKEN_FILENAME

    _write_private_json(bridge_config, bridge_raw)
    _write_private_text(go2rtc_config, _go2rtc_config(settings.cameras, log_level))
    _ensure_control_state(control_state, settings.cameras)
    _ensure_control_token(control_token)
    return RuntimeFiles(bridge_config, go2rtc_config, control_state, control_token)


def register_discovery(runtime: RuntimeFiles, supervisor_url: str = "http://supervisor") -> None:
    """Publish the app endpoints to the custom integration.

    These app-local endpoints bypass the app role permission, but Supervisor
    still authenticates the request with the token injected into the app.
    The camera control token is sent only in the discovery JSON body.
    """
    base_url = supervisor_url.rstrip("/")
    info = _request_json(f"{base_url}/addons/self/info")
    data = info.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("hostname"), str):
        raise ValueError("Supervisor app info did not include hostname")
    hostname = data["hostname"].replace("_", "-")
    token = runtime.control_token.read_text(encoding="utf-8").strip()
    _request_json(
        f"{base_url}/discovery",
        {
            "service": DISCOVERY_SERVICE,
            "config": {
                "host": hostname,
                "http_port": 8080,
                "rtsp_port": 8554,
                "token": token,
            },
        },
    )


def _request_json(url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if supervisor_token := os.environ.get("SUPERVISOR_TOKEN"):
        headers["Authorization"] = f"Bearer {supervisor_token}"
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=5) as response:  # noqa: S310 - Supervisor URL is fixed by app runtime
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Supervisor returned a non-object response")
    return result


def _go2rtc_config(cameras: tuple[Any, ...], log_level: str) -> str:
    lines = [
        "log:",
        "  format: text",
        f"  level: {log_level}",
        "api:",
        '  listen: "127.0.0.1:1984"',
        "rtsp:",
        '  listen: ":8554"',
        "ffmpeg:",
        "  timeout: 30",
        "streams:",
    ]
    for camera in cameras:
        lines.extend(
            [
                f"  ino_a9_{camera.name}:",
                f"    - ffmpeg:http://127.0.0.1:8080/{camera.name}/stream.mjpeg#video=h264",
                "    - exec:ffmpeg -hide_banner -loglevel warning -re -f alaw -ar 8000 -ac 1 "
                f"-i http://127.0.0.1:8080/{camera.name}/audio.alaw -vn -c:a libopus "
                "-application lowdelay -ar 48000 -ac 1 -rtsp_transport tcp -f rtsp {output}",
            ]
        )
    return "\n".join(lines) + "\n"


def _ensure_control_token(path: Path) -> None:
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        os.chmod(path, 0o600)
        return
    _write_private_text(path, secrets.token_urlsafe(32) + "\n")


def _ensure_control_state(path: Path, cameras: tuple[Any, ...]) -> None:
    existing: dict[str, object] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("cameras"), dict):
                existing = raw["cameras"]
        except json.JSONDecodeError:
            pass
    state = {
        "version": 1,
        "cameras": {
            camera.name: existing.get(camera.name, {})
            for camera in cameras
        },
    }
    _write_private_json(path, state)


def _write_private_json(path: Path, value: object) -> None:
    _write_private_text(path, json.dumps(value, separators=(",", ":")) + "\n")


def _write_private_text(path: Path, value: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(value)
        temporary.flush()
        os.fchmod(temporary.fileno(), 0o600)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare INO-A9 Home Assistant app runtime")
    parser.add_argument("--options", default="/data/options.json")
    parser.add_argument("--data-dir", default="/data")
    parser.add_argument("--supervisor-url", default="http://supervisor")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runtime = prepare_runtime(args.options, args.data_dir)
    try:
        register_discovery(runtime, args.supervisor_url)
    except Exception as error:  # The bridge can operate while Supervisor restarts.
        LOGGER.warning("Supervisor discovery registration failed: %s", type(error).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
