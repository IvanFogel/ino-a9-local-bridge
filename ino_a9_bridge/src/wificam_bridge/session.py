"""One reconnecting PPRPC reader shared by media and control operations."""

from __future__ import annotations

from threading import Event, Lock, Thread, current_thread
from typing import Callable

from .camera import CameraError, decrypt_rpc_payload
from .commands import (
    FLIP_GET_COMMAND,
    FLIP_SET_COMMAND,
    FLIP_VALUES,
    INTRUSION_COMMAND,
    MOTION_COMMAND,
    NIGHT_GET_COMMAND,
    NIGHT_SET_COMMAND,
    NIGHT_VALUES,
    REBOOT_COMMAND,
    STATUS_LED_COMMAND,
    VIDEO_QUALITY_COMMAND,
    build_flip_payload,
    build_intrusion_payload,
    build_led_payload,
    build_motion_payload,
    build_night_payload,
    build_video_quality_payload,
    read_response_value,
)
from .controls import IntrusionSchedule


class CameraUnavailable(CameraError):
    """Raised when a control is requested while the shared session reconnects."""


class CameraSession:
    """Keep one background reader and connection for camera media and controls."""

    def __init__(
        self,
        client,
        *,
        start_audio: bool = True,
        reconnect_delay: float = 1.0,
    ) -> None:
        if reconnect_delay < 0:
            raise ValueError("reconnect_delay must not be negative")
        self.client = client
        self._start_audio = start_audio
        self._reconnect_delay = reconnect_delay
        self._state_lock = Lock()
        self._control_lock = Lock()
        self._stop = Event()
        self._connected = Event()
        self._started = False
        self._thread: Thread | None = None
        self._on_frame: Callable[[bytes], None] | None = None
        self._on_audio: Callable[[bytes], None] | None = None
        self._error: Exception | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def error(self) -> Exception | None:
        with self._state_lock:
            return self._error

    def start(
        self,
        *,
        on_frame: Callable[[bytes], None] | None = None,
        on_audio: Callable[[bytes], None] | None = None,
    ) -> None:
        with self._state_lock:
            if self._started:
                raise CameraError("camera session has already started")
            self._started = True
            self._on_frame = on_frame
            self._on_audio = on_audio
            self._thread = Thread(target=self._reader_main, name="ino-a9-session", daemon=True)
            self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self.client.close()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2)
        self._connected.clear()

    def set_status_led(self, enabled: bool) -> None:
        self._send(STATUS_LED_COMMAND, build_led_payload(enabled))

    def set_night_vision(self, value: str) -> None:
        self._send(NIGHT_SET_COMMAND, build_night_payload(value))

    def get_night_vision(self) -> str:
        return self._get(NIGHT_GET_COMMAND, NIGHT_VALUES, "night vision")

    def set_flip(self, value: str) -> None:
        self._send(FLIP_SET_COMMAND, build_flip_payload(value))

    def get_flip(self) -> str:
        return self._get(FLIP_GET_COMMAND, FLIP_VALUES, "flip")

    def set_video_quality(self, value: str) -> None:
        self._send(VIDEO_QUALITY_COMMAND, build_video_quality_payload(value))

    def set_motion(self, value: str) -> None:
        self._send(MOTION_COMMAND, build_motion_payload(value))

    def set_intrusion(self, enabled: bool, schedule: IntrusionSchedule) -> None:
        self._send(INTRUSION_COMMAND, build_intrusion_payload(enabled, schedule))

    def reboot(self) -> None:
        self._require_connected()
        with self._control_lock:
            self.client.send_command(REBOOT_COMMAND)

    def _get(self, command: int, values: dict[str, int], label: str) -> str:
        response = self._send(command, b"")
        payload = decrypt_rpc_payload(response, self.client.credentials.bootstrap_prefix)
        wire_value = read_response_value(payload)
        reverse = {wire: name for name, wire in values.items()}
        if wire_value not in reverse:
            raise CameraError(f"unsupported {label} response")
        return reverse[wire_value]

    def _send(self, command: int, payload: bytes):
        self._require_connected()
        with self._control_lock:
            self._require_connected()
            return self.client.send_control(command, payload)

    def _require_connected(self) -> None:
        if not self._started or not self._connected.is_set():
            raise CameraUnavailable("camera session is reconnecting")

    def _reader_main(self) -> None:
        while not self._stop.is_set():
            try:
                self.client.connect()
                if self._start_audio:
                    self.client.start_audio()
                self._connected.set()
                for frame in self.client.frames(audio_callback=self._on_audio):
                    if self._on_frame is not None:
                        self._on_frame(frame)
                    if self._stop.is_set():
                        break
            except Exception as error:  # reconnecting is the expected recovery path
                with self._state_lock:
                    self._error = error
            finally:
                self._connected.clear()
                self.client.close()
            if not self._stop.is_set():
                self._stop.wait(self._reconnect_delay)
