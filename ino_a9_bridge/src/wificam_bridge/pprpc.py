"""Strict, dependency-free parsing for the observable PPRPC packet headers.

This is a clean Python implementation based on the wire format documented by
the archived Apache-2.0 ``github.com/pprpc/core/packets`` module. It performs no
network operations and deliberately does not contain an encryption secret.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Final


UDP_MAGIC: Final = b"Qp"
SUPPORTED_TYPES: Final = frozenset(range(3, 9))
SUPPORTED_FLAGS: Final = frozenset((8, 9, 10))
MAX_VARINT_BYTES: Final = 10


class PacketError(ValueError):
    """Raised when a packet is truncated or violates the known framing."""


@dataclass(frozen=True, slots=True)
class FixedHeader:
    message_type: int
    flag: int
    length: int
    is_udp: bool
    size: int


@dataclass(frozen=True, slots=True)
class RPCPacket:
    header: FixedHeader
    sequence: int
    command_id: int
    encryption_type: int
    rpc_type: int
    response_code: int | None
    payload: bytes


@dataclass(frozen=True, slots=True)
class AVPacket:
    header: FixedHeader
    is_key_frame: bool
    media_format: int
    encryption_type: int
    channel: int
    sequence: int
    timestamp: int
    encrypted_length: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class RawPacket:
    header: FixedHeader
    payload: bytes


def decode_varint(data: bytes, offset: int = 0, *, max_bytes: int = MAX_VARINT_BYTES) -> tuple[int, int]:
    """Decode one unsigned protobuf-style varint and return value/new offset."""
    value = 0
    for index in range(max_bytes):
        if offset >= len(data):
            raise PacketError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << (7 * index)
        if byte < 0x80:
            return value, offset
    raise PacketError("varint exceeds supported size")


def encode_varint(value: int) -> bytes:
    """Encode a non-negative integer using protobuf varint encoding."""
    if value < 0:
        raise ValueError("varint value must be non-negative")
    output = bytearray()
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)



def derive_rpc_key(prefix: str | bytes, sequence: int, command_id: int, rpc_type: int) -> bytes:
    """Derive the legacy 32-byte ASCII-hex AES key for an RPC payload.

    ``prefix`` must be supplied at runtime. This repository intentionally does
    not embed the vendor/device secret.
    """
    prefix_bytes = prefix.encode() if isinstance(prefix, str) else prefix
    suffix = f",ID:{command_id}-SEQ:{sequence}-RPC:{rpc_type}".encode()
    return hashlib.md5(prefix_bytes + suffix).hexdigest().encode()


def derive_av_key(prefix: str | bytes, sequence: int, timestamp: int, channel: int) -> bytes:
    """Derive the legacy 32-byte ASCII-hex AES key for an AV payload."""
    prefix_bytes = prefix.encode() if isinstance(prefix, str) else prefix
    suffix = f",AVSeq:{sequence}-TT:{timestamp}-AVChannel:{channel}".encode()
    return hashlib.md5(prefix_bytes + suffix).hexdigest().encode()

def parse_fixed_header(data: bytes, *, udp: bool | None = None) -> tuple[FixedHeader, int]:
    """Parse a PPRPC fixed header.

    When ``udp`` is ``None``, the ``Qp`` prefix is auto-detected. Setting it to
    ``True`` requires the prefix; setting it to ``False`` treats the first byte
    as the type/flag byte.
    """
    offset = 0
    detected_udp = data.startswith(UDP_MAGIC)
    if udp is True and not detected_udp:
        raise PacketError("missing UDP magic 0x5170")
    is_udp = detected_udp if udp is None else udp
    if is_udp:
        if not detected_udp:
            raise PacketError("missing UDP magic 0x5170")
        offset = len(UDP_MAGIC)
    if offset >= len(data):
        raise PacketError("missing type/flag byte")
    type_and_flag = data[offset]
    offset += 1
    message_type = type_and_flag >> 4
    flag = type_and_flag & 0x0F
    if message_type not in SUPPORTED_TYPES:
        raise PacketError(f"unsupported message type {message_type}")
    if flag not in SUPPORTED_FLAGS:
        raise PacketError(f"unsupported flag {flag}")
    length, offset = decode_varint(data, offset, max_bytes=4)
    return FixedHeader(message_type, flag, length, is_udp, offset), offset


def parse_packet(data: bytes, *, udp: bool | None = None, exact: bool = True) -> RPCPacket | AVPacket | RawPacket:
    """Parse one complete PPRPC packet without decrypting its payload."""
    header, offset = parse_fixed_header(data, udp=udp)
    end = offset + header.length
    if end > len(data):
        raise PacketError(f"truncated packet: declared {header.length} body bytes, have {len(data) - offset}")
    if exact and end != len(data):
        raise PacketError(f"trailing data: {len(data) - end} bytes")
    body = data[offset:end]
    if header.message_type in (4, 5):
        return _parse_rpc(header, body)
    if header.message_type == 6:
        return _parse_av(header, body)
    return RawPacket(header, body)



def iter_tcp_packets(data: bytes) -> tuple[list[RPCPacket | AVPacket | RawPacket], bytes]:
    """Parse all complete PPRPC packets from a TCP byte stream.

    Returns ``(packets, remainder)``. A final incomplete packet is returned as
    remainder rather than treated as an error, which is convenient for socket
    receive buffers.
    """
    packets: list[RPCPacket | AVPacket | RawPacket] = []
    offset = 0
    while offset < len(data):
        try:
            header, body_offset = parse_fixed_header(data[offset:], udp=False)
        except PacketError as error:
            if "truncated" in str(error) or "missing" in str(error):
                break
            raise
        packet_size = body_offset + header.length
        if len(data) - offset < packet_size:
            break
        packets.append(parse_packet(data[offset : offset + packet_size], udp=False))
        offset += packet_size
    return packets, data[offset:]

def _parse_rpc(header: FixedHeader, body: bytes) -> RPCPacket:
    cursor = 0
    sequence, cursor = decode_varint(body, cursor, max_bytes=4)
    command_id, cursor = decode_varint(body, cursor, max_bytes=4)
    if cursor >= len(body):
        raise PacketError("RPC packet missing encryption/type byte")
    flags = body[cursor]
    cursor += 1
    encryption_type = flags >> 2
    rpc_type = flags & 0x03
    if rpc_type not in (0, 1):
        raise PacketError(f"unsupported RPC type {rpc_type}")
    response_code = None
    if rpc_type == 1:
        response_code, cursor = decode_varint(body, cursor, max_bytes=4)
    return RPCPacket(
        header,
        sequence,
        command_id,
        encryption_type,
        rpc_type,
        response_code,
        body[cursor:],
    )


def _parse_av(header: FixedHeader, body: bytes) -> AVPacket:
    if len(body) < 2:
        raise PacketError("AV packet missing format/encryption bytes")
    format_byte = body[0]
    encryption_type = body[1]
    cursor = 2
    channel, cursor = decode_varint(body, cursor, max_bytes=4)
    sequence, cursor = decode_varint(body, cursor, max_bytes=4)
    timestamp, cursor = decode_varint(body, cursor, max_bytes=9)
    encrypted_length, cursor = decode_varint(body, cursor, max_bytes=4)
    return AVPacket(
        header,
        bool(format_byte >> 7),
        format_byte & 0x7F,
        encryption_type,
        channel,
        sequence,
        timestamp,
        encrypted_length,
        body[cursor:],
    )
