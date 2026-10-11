from __future__ import annotations

import pytest

from wificam_bridge.camera import (
    DEFAULT_FRAME_TIMEOUT_SECONDS,
    G711_ALAW_FORMAT,
    TIME_SYNC_COMMAND,
    CameraClient,
    CameraError,
    CameraCredentials,
    MJPEGReassembler,
    VIDEO_MAX_QOS,
    build_lan_auth_request,
    build_time_request_payload,
    build_time_sync_response,
    decrypt_rpc_payload,
    encode_protobuf_varint,
    extract_g711_alaw_payload,
    pack_rpc,
)
from wificam_bridge.crypto import aes_cbc_encrypt_unpadded
from wificam_bridge.pprpc import AVPacket, FixedHeader, RPCPacket, derive_av_key, parse_packet


def _varints(payload: bytes) -> list[tuple[int, int]]:
    values: list[tuple[int, int]] = []
    offset = 0
    while offset < len(payload):
        tag, offset = _varint(payload, offset)
        value, offset = _varint(payload, offset)
        values.append((tag >> 3, value))
    return values


def _varint(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        byte = payload[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
    raise AssertionError("oversized test varint")


def test_extract_g711_alaw_payload_strips_transport_prefix() -> None:
    packet = AVPacket(
        FixedHeader(6, 9, 0, False, 2),
        False,
        G711_ALAW_FORMAT,
        0,
        0,
        10,
        20,
        0,
        b"\x01\x00\xd5\x55",
    )

    assert extract_g711_alaw_payload(packet) == b"\xd5\x55"


def test_rpc_encrypt_pack_parse_decrypt_round_trip() -> None:
    prefix = b"synthetic-bootstrap-prefix"
    plaintext = b"\x08\x01"
    raw = pack_rpc(
        sequence=4,
        command_id=106,
        plaintext=plaintext,
        prefix=prefix,
    )
    parsed = parse_packet(raw, udp=False)
    assert isinstance(parsed, RPCPacket)
    assert parsed.sequence == 4
    assert parsed.command_id == 106
    assert decrypt_rpc_payload(parsed, prefix) == plaintext


def test_lan_auth_request_omits_default_channel() -> None:
    credentials = CameraCredentials(b"prefix", "synthetic-user", "$LS$synthetic-token")
    payload = build_lan_auth_request(credentials)
    assert payload.startswith(b"\x12")
    assert b"synthetic-user" in payload
    assert b"$LS$synthetic-token" in payload


def test_time_sync_response_copies_request_timestamp() -> None:
    request = encode_protobuf_varint(1, 123456) + encode_protobuf_varint(2, 1)
    response = build_time_sync_response(request, now_ms=789012)
    assert _varints(response) == [
        (1, 123456),
        (2, (1 << 64) - 30),
        (3, 789012),
    ]


def test_time_request_payload_includes_latest_av_sequence() -> None:
    payload = build_time_request_payload(123456, ans_seq=789)

    assert _varints(payload) == [(1, 123456), (4, 789)]


def test_maximum_video_qos_request() -> None:
    assert _varints(encode_protobuf_varint(2, VIDEO_MAX_QOS)) == [(2, 30)]


def test_mjpeg_reassembler_uses_first_fragment_metadata_and_trims_trailer() -> None:
    prefix = b"0123456789abcdef0123456789abcdef"
    jpeg = b"\xff\xd8" + b"J" * 1496 + b"\xff\xd9"
    framed = jpeg + b"trail"
    timestamp = 123456789
    sequence = 7
    encrypted_length = 1040
    key = derive_av_key(prefix, sequence, timestamp, 0)
    wire = (
        aes_cbc_encrypt_unpadded(framed[:encrypted_length], key, key[-16:])
        + framed[encrypted_length:]
    )
    chunks = [wire[index : index + 400] for index in range(0, len(wire), 400)]
    header = FixedHeader(6, 10, 0, False, 0)
    reassembler = MJPEGReassembler(prefix)
    result = None
    for index, chunk in enumerate(chunks, start=1):
        final = index == len(chunks)
        packet = AVPacket(
            header=header,
            is_key_frame=False,
            media_format=4,
            encryption_type=3,
            channel=0,
            sequence=sequence,
            timestamp=timestamp if index == 1 else timestamp + index,
            encrypted_length=encrypted_length if index == 1 else 0,
            payload=bytes((1, 0xFF if final else index, 0)) + chunk,
        )
        result = reassembler.push(packet)
    assert result == jpeg


def test_mjpeg_reassembler_drops_out_of_order_fragments() -> None:
    prefix = b"0123456789abcdef0123456789abcdef"
    header = FixedHeader(6, 10, 0, False, 0)
    reassembler = MJPEGReassembler(prefix)
    first = AVPacket(header, False, 4, 3, 0, 1, 1, 16, b"\x01\x01\x00" + b"A" * 16)
    third = AVPacket(header, False, 4, 3, 0, 1, 1, 0, b"\x01\x03\x00" + b"B" * 16)
    assert reassembler.push(first) is None
    assert reassembler.push(third) is None


def test_camera_client_times_out_stalled_stream() -> None:
    client = CameraClient(
        "camera.invalid",
        CameraCredentials(b"prefix", "user", "password"),
        frame_timeout=0.001,
    )
    client._socket = object()  # type: ignore[assignment]
    client._session_prefix = b"0123456789abcdef0123456789abcdef"
    client._receive = lambda _deadline: []  # type: ignore[method-assign]

    with pytest.raises(TimeoutError, match="no activity"):
        next(client.frames())


def test_camera_client_default_timeout_keeps_video_recovery_short() -> None:
    client = CameraClient(
        "camera.invalid",
        CameraCredentials(b"prefix", "user", "password"),
    )

    assert DEFAULT_FRAME_TIMEOUT_SECONDS == 2.0
    assert client.frame_timeout == DEFAULT_FRAME_TIMEOUT_SECONDS


def test_camera_client_sends_av_ack_heartbeat(monkeypatch) -> None:
    client = CameraClient(
        "camera.invalid",
        CameraCredentials(b"prefix", "user", "password"),
        frame_timeout=10.0,
    )
    client._socket = object()  # type: ignore[assignment]
    client._session_prefix = b"0123456789abcdef0123456789abcdef"
    audio_packet = AVPacket(
        FixedHeader(6, 9, 0, False, 2),
        False,
        G711_ALAW_FORMAT,
        0,
        0,
        42,
        20,
        0,
        b"\x01\x00audio",
    )
    sent: list[tuple[int, int, bytes]] = []
    receives = 0
    clock = 0.0

    def monotonic() -> float:
        return clock

    def receive(_deadline):
        nonlocal receives, clock
        receives += 1
        if receives == 1:
            clock = 0.1
            return [audio_packet]
        if receives == 2:
            clock = 0.6
            return []
        raise CameraError("end of test stream")

    monkeypatch.setattr("wificam_bridge.camera.time.monotonic", monotonic)
    client._receive = receive  # type: ignore[method-assign]
    client._send_request = (  # type: ignore[method-assign]
        lambda sequence, command_id, payload: sent.append((sequence, command_id, payload))
    )

    with pytest.raises(CameraError, match="end of test stream"):
        next(client.frames())

    assert len(sent) == 1
    assert sent[0][0] == 5
    assert sent[0][1] == TIME_SYNC_COMMAND
    assert _varints(sent[0][2])[1] == (4, 42)


def test_camera_client_refreshes_video_session_while_audio_arrives(monkeypatch) -> None:
    client = CameraClient(
        "camera.invalid",
        CameraCredentials(b"prefix", "user", "password"),
        frame_timeout=10.0,
    )
    client._socket = object()  # type: ignore[assignment]
    client._session_prefix = b"0123456789abcdef0123456789abcdef"
    audio_packet = AVPacket(
        FixedHeader(6, 9, 0, False, 2),
        False,
        G711_ALAW_FORMAT,
        0,
        0,
        10,
        20,
        0,
        b"\x01\x00audio",
    )
    audio: list[bytes] = []
    receives = 0
    clock = 0.0

    def monotonic() -> float:
        return clock

    def receive(_deadline):
        nonlocal receives, clock
        receives += 1
        if receives <= 2:
            clock = receives / 10
            return [audio_packet]
        clock = 10.1
        return []

    monkeypatch.setattr("wificam_bridge.camera.time.monotonic", monotonic)
    client._receive = receive  # type: ignore[method-assign]
    client._send_request = lambda *_args: None  # type: ignore[method-assign]

    with pytest.raises(TimeoutError, match="no complete frame"):
        next(client.frames(audio_callback=audio.append))

    assert audio == [b"audio"] * 2
