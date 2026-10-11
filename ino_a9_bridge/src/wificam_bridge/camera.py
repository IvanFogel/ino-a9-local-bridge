"""Independent LAN client for the Linklemo/INO-A9 PPRPC camera."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import socket
import string
from threading import Event, Lock
import time
from typing import Callable, Iterator

from .crypto import (
    aes_cbc_decrypt_padded,
    aes_cbc_decrypt_unpadded,
    aes_cbc_encrypt_padded,
)
from .pprpc import (
    AVPacket,
    RPCPacket,
    RawPacket,
    derive_av_key,
    derive_rpc_key,
    encode_varint,
    iter_tcp_packets,
)


LAN_AUTH_COMMAND = 2650
SYNC_COMMAND = 106
TIME_SYNC_COMMAND = 107
VIDEO_START_COMMAND = 2610
AUDIO_START_COMMAND = 2614
VIDEO_MAX_QOS = 30
AES_256_CBC = 3
RPC_REQUEST = 0
RPC_RESPONSE = 1
MJPEG_FORMAT = 4
G711_ALAW_FORMAT = 21
G711_ALAW_SAMPLE_RATE = 8000
G711_ALAW_TRANSPORT_PREFIX = b"\x01\x00"
# The tested firmware can leave video idle while audio continues on the same
# socket. Two seconds is the lowest value that still lets a fresh session
# deliver its first complete JPEG; it keeps recovery short for existing
# viewers, while CameraState's separate grace window prevents HA flapping.
DEFAULT_FRAME_TIMEOUT_SECONDS = 2.0
HEARTBEAT_INTERVAL_SECONDS = 0.5


@dataclass(slots=True)
class _PendingCommand:
    event: Event
    response: RPCPacket | None = None
    error: Exception | None = None


class CameraError(RuntimeError):
    """Raised when the camera rejects or violates the LAN protocol."""


@dataclass(frozen=True, slots=True)
class CameraCredentials:
    """Private values learned during an authorized one-time pairing capture."""

    bootstrap_prefix: bytes
    user: str
    lan_password: str

    def __post_init__(self) -> None:
        if not self.bootstrap_prefix:
            raise ValueError("bootstrap_prefix must not be empty")
        if not self.user:
            raise ValueError("user must not be empty")
        if not self.lan_password:
            raise ValueError("lan_password must not be empty")


def encode_protobuf_varint(field_number: int, value: int) -> bytes:
    """Encode one protobuf varint field, including signed int64 bit patterns."""
    if field_number <= 0:
        raise ValueError("protobuf field number must be positive")
    return encode_varint(field_number << 3) + encode_varint(value & ((1 << 64) - 1))


def encode_protobuf_bytes(field_number: int, value: bytes) -> bytes:
    """Encode one protobuf length-delimited field."""
    if field_number <= 0:
        raise ValueError("protobuf field number must be positive")
    return encode_varint((field_number << 3) | 2) + encode_varint(len(value)) + value


def build_lan_auth_request(credentials: CameraCredentials) -> bytes:
    """Build ``LanAuth.Req`` without exposing its values in logs or arguments."""
    return (
        encode_protobuf_bytes(2, credentials.user.encode("utf-8"))
        + encode_protobuf_bytes(3, credentials.lan_password.encode("utf-8"))
    )


def build_time_sync_response(request_payload: bytes, *, now_ms: int | None = None) -> bytes:
    """Build the command-107 response expected before video can start."""
    request_timestamp = _first_varint_field(request_payload, field_number=1)
    current = int(time.time() * 1000) if now_ms is None else now_ms
    return (
        encode_protobuf_varint(1, request_timestamp)
        + encode_protobuf_varint(2, -30)
        + encode_protobuf_varint(3, current)
    )


def build_time_request_payload(now_ms: int, *, ans_seq: int | None = None) -> bytes:
    """Build the client heartbeat and optionally acknowledge the latest AV packet."""
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms < 0:
        raise ValueError("now_ms must be a non-negative integer")
    if ans_seq is not None and (
        not isinstance(ans_seq, int) or isinstance(ans_seq, bool) or ans_seq < 0
    ):
        raise ValueError("ans_seq must be a non-negative integer")

    payload = encode_protobuf_varint(1, now_ms)
    if ans_seq is not None:
        payload += encode_protobuf_varint(4, ans_seq)
    return payload


def pack_rpc(
    *,
    sequence: int,
    command_id: int,
    plaintext: bytes,
    prefix: bytes,
    rpc_type: int = RPC_REQUEST,
    response_code: int = 0,
) -> bytes:
    """Pack one encrypted PPRPC protobuf command."""
    if rpc_type not in (RPC_REQUEST, RPC_RESPONSE):
        raise ValueError("rpc_type must be request (0) or response (1)")
    payload = b""
    if plaintext:
        key = derive_rpc_key(prefix, sequence, command_id, rpc_type)
        payload = aes_cbc_encrypt_padded(plaintext, key, key[:16])
    body = (
        encode_varint(sequence)
        + encode_varint(command_id)
        + bytes(((AES_256_CBC << 2) | rpc_type,))
    )
    if rpc_type == RPC_RESPONSE:
        body += encode_varint(response_code)
    body += payload
    return b"\x48" + encode_varint(len(body)) + body


def decrypt_rpc_payload(packet: RPCPacket, prefix: bytes) -> bytes:
    """Decrypt one RPC payload using the control-plane prefix."""
    if not packet.payload:
        return b""
    if packet.encryption_type != AES_256_CBC:
        raise CameraError(f"unsupported RPC encryption type {packet.encryption_type}")
    key = derive_rpc_key(prefix, packet.sequence, packet.command_id, packet.rpc_type)
    return aes_cbc_decrypt_padded(packet.payload, key, key[:16])


def extract_g711_alaw_payload(packet: AVPacket) -> bytes | None:
    """Return raw G.711 A-law bytes from a validated live-audio packet."""
    if (
        packet.media_format != G711_ALAW_FORMAT
        or packet.channel != 0
        or packet.encryption_type != 0
        or not packet.payload.startswith(G711_ALAW_TRANSPORT_PREFIX)
    ):
        return None
    payload = packet.payload[len(G711_ALAW_TRANSPORT_PREFIX) :]
    return payload or None


class MJPEGReassembler:
    """Reassemble and decrypt the camera's fragmented MJPEG AV packets."""

    def __init__(self, session_prefix: bytes, *, max_frame_bytes: int = 2_000_000) -> None:
        if len(session_prefix) != 32:
            raise ValueError("AV session prefix must contain 32 bytes")
        self._session_prefix = session_prefix
        self._max_frame_bytes = max_frame_bytes
        self._fragments: dict[int, list[bytes]] = defaultdict(list)
        self._sizes: dict[int, int] = defaultdict(int)
        self._metadata: dict[int, AVPacket] = {}
        self._expected_index: dict[int, int] = {}

    def push(self, packet: AVPacket) -> bytes | None:
        if packet.media_format != MJPEG_FORMAT or len(packet.payload) < 3:
            return None
        marker, fragment_index, reserved = packet.payload[:3]
        if marker != 1 or reserved != 0:
            self._drop(packet.sequence)
            return None

        sequence = packet.sequence
        if fragment_index == 1:
            self._drop(sequence)
            self._expected_index[sequence] = 1
        expected = self._expected_index.get(sequence)
        if expected is None:
            return None
        if fragment_index != 0xFF and fragment_index != expected:
            self._drop(sequence)
            return None

        fragment = packet.payload[3:]
        self._fragments[sequence].append(fragment)
        self._sizes[sequence] += len(fragment)
        if self._sizes[sequence] > self._max_frame_bytes:
            self._drop(sequence)
            return None
        if packet.encrypted_length:
            self._metadata.setdefault(sequence, packet)
        if fragment_index != 0xFF:
            self._expected_index[sequence] = expected + 1
            return None

        fragments = self._fragments.pop(sequence)
        self._sizes.pop(sequence, None)
        self._expected_index.pop(sequence, None)
        metadata = self._metadata.pop(sequence, None)
        if metadata is None:
            return None
        assembled = b"".join(fragments)
        encrypted_length = metadata.encrypted_length
        if (
            encrypted_length <= 0
            or encrypted_length > len(assembled)
            or encrypted_length % 16
        ):
            return None
        key = derive_av_key(
            self._session_prefix,
            metadata.sequence,
            metadata.timestamp,
            metadata.channel,
        )
        head = aes_cbc_decrypt_unpadded(assembled[:encrypted_length], key, key[-16:])
        frame = head + assembled[encrypted_length:]
        if not frame.startswith(b"\xff\xd8"):
            return None
        eoi = frame.find(b"\xff\xd9", 2)
        if eoi < 0:
            return None
        return frame[: eoi + 2]

    def _drop(self, sequence: int) -> None:
        self._fragments.pop(sequence, None)
        self._sizes.pop(sequence, None)
        self._metadata.pop(sequence, None)
        self._expected_index.pop(sequence, None)


class CameraClient:
    """Connect, authenticate, start MJPEG, and yield complete JPEG images."""

    def __init__(
        self,
        host: str,
        credentials: CameraCredentials,
        *,
        port: int = 20190,
        connect_timeout: float = 5.0,
        frame_timeout: float = DEFAULT_FRAME_TIMEOUT_SECONDS,
        control_timeout: float | None = None,
        socket_factory: Callable[[tuple[str, int], float], socket.socket] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.credentials = credentials
        self.connect_timeout = connect_timeout
        if frame_timeout <= 0:
            raise ValueError("frame_timeout must be positive")
        self.frame_timeout = frame_timeout
        if control_timeout is not None and control_timeout <= 0:
            raise ValueError("control_timeout must be positive")
        self.control_timeout = connect_timeout if control_timeout is None else control_timeout
        self.socket_factory = socket.create_connection if socket_factory is None else socket_factory
        self._socket: socket.socket | None = None
        self._buffer = b""
        self._pending: deque[RPCPacket | AVPacket | RawPacket] = deque()
        self._session_prefix: bytes | None = None
        self._send_lock = Lock()
        self._sequence_lock = Lock()
        self._pending_commands_lock = Lock()
        self._pending_commands: dict[tuple[int, int], _PendingCommand] = {}
        self._next_sequence = 5

    def connect(self) -> None:
        self.close()
        sock = self.socket_factory((self.host, self.port), self.connect_timeout)
        sock.settimeout(1.0)
        self._socket = sock
        self._buffer = b""
        self._pending.clear()
        self._next_sequence = 5
        try:
            self._send_request(1, LAN_AUTH_COMMAND, build_lan_auth_request(self.credentials))
            auth = self._wait_response(1, LAN_AUTH_COMMAND)
            session_prefix = _first_bytes_field(
                decrypt_rpc_payload(auth, self.credentials.bootstrap_prefix),
                field_number=1,
            )
            if len(session_prefix) != 32 or any(
                chr(byte) not in string.hexdigits for byte in session_prefix
            ):
                raise CameraError("LAN authentication returned an invalid session prefix")
            self._session_prefix = session_prefix

            self._send_request(2, SYNC_COMMAND, encode_protobuf_varint(1, 1))
            self._wait_response(2, SYNC_COMMAND)
            self._answer_initial_time_syncs()

            # Ask for the SDK's highest defined QoS. Cameras clamp this to
            # their own maximum; the tested INO-A9 reports QoS 5 (640x480).
            self._send_request(
                3,
                VIDEO_START_COMMAND,
                encode_protobuf_varint(2, VIDEO_MAX_QOS),
            )
            self._wait_response(3, VIDEO_START_COMMAND)
        except Exception:
            self.close()
            raise

    def start_audio(self) -> None:
        """Request the camera's live microphone stream on channel zero."""
        if self._socket is None:
            raise CameraError("camera is not connected")
        self._send_request(4, AUDIO_START_COMMAND, b"")
        response = self._wait_response(4, AUDIO_START_COMMAND)
        payload = decrypt_rpc_payload(response, self.credentials.bootstrap_prefix)
        media_format = _first_varint_field(payload, field_number=5)
        sample_rate = _first_varint_field(payload, field_number=6)
        if media_format != G711_ALAW_FORMAT or sample_rate != G711_ALAW_SAMPLE_RATE:
            raise CameraError(
                f"unsupported camera audio format {media_format} at {sample_rate} Hz"
            )

    def frames(
        self,
        *,
        audio_callback: Callable[[bytes], None] | None = None,
    ) -> Iterator[bytes]:
        if self._socket is None or self._session_prefix is None:
            raise CameraError("camera is not connected")
        reassembler = MJPEGReassembler(self._session_prefix)
        activity_deadline = time.monotonic() + self.frame_timeout
        frame_deadline = activity_deadline
        next_heartbeat = time.monotonic() + HEARTBEAT_INTERVAL_SECONDS
        latest_av_sequence: int | None = None
        try:
            while self._socket is not None:
                now = time.monotonic()
                if now >= next_heartbeat:
                    self._send_request(
                        self._allocate_sequence(),
                        TIME_SYNC_COMMAND,
                        build_time_request_payload(
                            int(time.time() * 1000),
                            ans_seq=latest_av_sequence,
                        ),
                    )
                    next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS
                if self._pending:
                    packets = [self._pending.popleft()]
                else:
                    packets = self._receive(
                        min(time.monotonic() + 2.0, activity_deadline, next_heartbeat)
                    )
                if packets:
                    activity_deadline = time.monotonic() + self.frame_timeout
                for packet in packets:
                    if isinstance(packet, RPCPacket):
                        if packet.rpc_type == RPC_RESPONSE and self._resolve_pending(packet):
                            continue
                        self._handle_rpc_request(packet)
                    elif isinstance(packet, AVPacket):
                        if latest_av_sequence is None or packet.sequence > latest_av_sequence:
                            latest_av_sequence = packet.sequence
                        if audio_callback is not None:
                            audio = extract_g711_alaw_payload(packet)
                            if audio is not None:
                                audio_callback(audio)
                        frame = reassembler.push(packet)
                        if frame is not None:
                            frame_deadline = time.monotonic() + self.frame_timeout
                            yield frame
                now = time.monotonic()
                if now >= activity_deadline:
                    raise TimeoutError(
                        f"camera stream produced no activity for "
                        f"{self.frame_timeout:g} seconds"
                    )
                if now >= frame_deadline:
                    raise TimeoutError(
                        f"camera stream produced no complete frame for "
                        f"{self.frame_timeout:g} seconds"
                    )
        finally:
            self._fail_pending(CameraError("camera stream stopped"))

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None
        self._session_prefix = None
        self._buffer = b""
        self._pending.clear()
        self._fail_pending(CameraError("camera connection closed"))

    def __enter__(self) -> CameraClient:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open_session(self, *, start_audio: bool = True):
        """Create a media-and-controls session over this camera connection."""
        from .session import CameraSession

        return CameraSession(self, start_audio=start_audio)

    def send_control(
        self,
        command_id: int,
        payload: bytes = b"",
        *,
        timeout: float | None = None,
    ) -> RPCPacket:
        """Send one control command and wait for the background reader response."""
        if not isinstance(command_id, int) or isinstance(command_id, bool) or command_id < 0:
            raise ValueError("command_id must be a non-negative integer")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        wait_timeout = self.control_timeout if timeout is None else timeout
        if not isinstance(wait_timeout, (int, float)) or wait_timeout <= 0:
            raise ValueError("timeout must be positive")
        sequence = self._allocate_sequence()
        pending = _PendingCommand(Event())
        key = (command_id, sequence)
        with self._pending_commands_lock:
            self._pending_commands[key] = pending
        try:
            self._send_request(sequence, command_id, payload)
        except Exception:
            with self._pending_commands_lock:
                self._pending_commands.pop(key, None)
            raise
        if not pending.event.wait(wait_timeout):
            with self._pending_commands_lock:
                self._pending_commands.pop(key, None)
            raise TimeoutError(f"camera did not answer control command {command_id}")
        with self._pending_commands_lock:
            self._pending_commands.pop(key, None)
        if pending.error is not None:
            raise pending.error
        response = pending.response
        if response is None:
            raise CameraError("control command completed without a response")
        if response.response_code != 0:
            raise CameraError(f"command {command_id} returned code {response.response_code}")
        return response

    def send_command(self, command_id: int, payload: bytes = b"") -> None:
        """Send a fire-and-forget camera command."""
        if not isinstance(command_id, int) or isinstance(command_id, bool) or command_id < 0:
            raise ValueError("command_id must be a non-negative integer")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        self._send_request(self._allocate_sequence(), command_id, payload)

    def _send_request(self, sequence: int, command_id: int, plaintext: bytes) -> None:
        self._send(
            pack_rpc(
                sequence=sequence,
                command_id=command_id,
                plaintext=plaintext,
                prefix=self.credentials.bootstrap_prefix,
            )
        )

    def _send(self, data: bytes) -> None:
        with self._send_lock:
            if self._socket is None:
                raise CameraError("camera socket is closed")
            self._socket.sendall(data)

    def _wait_response(self, sequence: int, command_id: int) -> RPCPacket:
        deadline = time.monotonic() + self.connect_timeout
        while time.monotonic() < deadline:
            found: RPCPacket | None = None
            for packet in self._receive(deadline):
                if (
                    isinstance(packet, RPCPacket)
                    and packet.rpc_type == RPC_RESPONSE
                    and packet.sequence == sequence
                    and packet.command_id == command_id
                ):
                    found = packet
                elif isinstance(packet, RPCPacket) and self._handle_rpc_request(packet):
                    continue
                else:
                    self._pending.append(packet)
            if found is not None:
                if found.response_code != 0:
                    raise CameraError(
                        f"command {command_id} returned code {found.response_code}"
                    )
                return found
        raise TimeoutError(f"camera did not answer command {command_id}")

    def _answer_initial_time_syncs(self) -> None:
        deadline = time.monotonic() + 2.0
        replies = 0
        while time.monotonic() < deadline and replies < 2:
            for packet in self._receive(deadline):
                if (
                    isinstance(packet, RPCPacket)
                    and packet.rpc_type == RPC_REQUEST
                    and packet.command_id == TIME_SYNC_COMMAND
                ):
                    self._handle_rpc_request(packet)
                    replies += 1
                else:
                    self._pending.append(packet)

    def _handle_rpc_request(self, packet: RPCPacket) -> bool:
        if packet.rpc_type != RPC_REQUEST or packet.command_id != TIME_SYNC_COMMAND:
            return False
        request = decrypt_rpc_payload(packet, self.credentials.bootstrap_prefix)
        response = build_time_sync_response(request)
        self._send(
            pack_rpc(
                sequence=packet.sequence,
                command_id=TIME_SYNC_COMMAND,
                plaintext=response,
                prefix=self.credentials.bootstrap_prefix,
                rpc_type=RPC_RESPONSE,
            )
        )
        return True

    def _receive(self, deadline: float) -> list[RPCPacket | AVPacket | RawPacket]:
        if self._socket is None:
            raise CameraError("camera socket is closed")
        while time.monotonic() < deadline:
            remaining = max(0.05, min(1.0, deadline - time.monotonic()))
            self._socket.settimeout(remaining)
            try:
                data = self._socket.recv(65536)
            except TimeoutError:
                continue
            if not data:
                raise CameraError("camera closed the connection")
            packets, self._buffer = iter_tcp_packets(self._buffer + data)
            if packets:
                return packets
        return []

    def _allocate_sequence(self) -> int:
        with self._sequence_lock:
            sequence = self._next_sequence
            self._next_sequence += 1
            return sequence

    def _resolve_pending(self, packet: RPCPacket) -> bool:
        with self._pending_commands_lock:
            pending = self._pending_commands.get((packet.command_id, packet.sequence))
        if pending is None:
            return False
        pending.response = packet
        pending.event.set()
        return True

    def _fail_pending(self, error: Exception) -> None:
        with self._pending_commands_lock:
            pending = tuple(self._pending_commands.values())
            self._pending_commands.clear()
        for command in pending:
            command.error = error
            command.event.set()


def _first_varint_field(payload: bytes, *, field_number: int) -> int:
    offset = 0
    while offset < len(payload):
        tag, offset = _decode_varint(payload, offset)
        number, wire_type = tag >> 3, tag & 7
        if wire_type != 0:
            raise CameraError("unexpected protobuf wire type")
        value, offset = _decode_varint(payload, offset)
        if number == field_number:
            return value
    raise CameraError(f"protobuf field {field_number} is missing")


def _first_bytes_field(payload: bytes, *, field_number: int) -> bytes:
    offset = 0
    while offset < len(payload):
        tag, offset = _decode_varint(payload, offset)
        number, wire_type = tag >> 3, tag & 7
        if wire_type != 2:
            raise CameraError("unexpected protobuf wire type")
        length, offset = _decode_varint(payload, offset)
        end = offset + length
        if end > len(payload):
            raise CameraError("truncated protobuf field")
        if number == field_number:
            return payload[offset:end]
        offset = end
    raise CameraError(f"protobuf field {field_number} is missing")


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise CameraError("truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise CameraError("oversized protobuf varint")
