import pytest

from wificam_bridge.pprpc import (
    AVPacket,
    PacketError,
    RPCPacket,
    decode_varint,
    derive_av_key,
    derive_rpc_key,
    encode_varint,
    iter_tcp_packets,
    parse_packet,
)


@pytest.mark.parametrize("value", [0, 1, 127, 128, 255, 16384, 268435455])
def test_varint_round_trip(value: int) -> None:
    encoded = encode_varint(value)
    decoded, offset = decode_varint(encoded)
    assert decoded == value
    assert offset == len(encoded)


def test_parse_tcp_rpc_request() -> None:
    body = encode_varint(129) + encode_varint(601) + bytes([(3 << 2) | 0]) + b"ciphertext"
    packet = parse_packet(bytes([0x48]) + encode_varint(len(body)) + body, udp=False)
    assert isinstance(packet, RPCPacket)
    assert packet.sequence == 129
    assert packet.command_id == 601
    assert packet.encryption_type == 3
    assert packet.rpc_type == 0
    assert packet.response_code is None
    assert packet.payload == b"ciphertext"


def test_parse_udp_rpc_response() -> None:
    body = b"\x00" + encode_varint(601) + bytes([(3 << 2) | 1]) + b"\x00" + b"reply"
    packet = parse_packet(b"Qp\x48" + encode_varint(len(body)) + body, udp=True)
    assert isinstance(packet, RPCPacket)
    assert packet.header.is_udp
    assert packet.response_code == 0
    assert packet.payload == b"reply"


def test_parse_h264_key_frame() -> None:
    payload = b"\x00\x00\x00\x01\x65frame"
    variable = bytes([0x80 | 1, 0])
    variable += encode_varint(0) + encode_varint(42) + encode_varint(123456) + encode_varint(0)
    body = variable + payload
    packet = parse_packet(b"\x68" + encode_varint(len(body)) + body, udp=False)
    assert isinstance(packet, AVPacket)
    assert packet.is_key_frame
    assert packet.media_format == 1
    assert packet.sequence == 42
    assert packet.timestamp == 123456
    assert packet.payload == payload


def test_parse_live_av_flag_10() -> None:
    body = bytes([10, 3])
    body += encode_varint(0) + encode_varint(7) + encode_varint(99) + encode_varint(1040)
    body += b"\x01\xff\x00fragment"
    packet = parse_packet(b"\x6a" + encode_varint(len(body)) + body, udp=False)
    assert isinstance(packet, AVPacket)
    assert packet.header.flag == 10
    assert packet.encryption_type == 3
    assert packet.encrypted_length == 1040
    assert packet.payload == b"\x01\xff\x00fragment"


def test_parse_live_audio_flag_9() -> None:
    body = bytes([21, 0])
    body += encode_varint(0) + encode_varint(8) + encode_varint(100) + encode_varint(0)
    body += b"audio"
    packet = parse_packet(b"\x69" + encode_varint(len(body)) + body, udp=False)
    assert isinstance(packet, AVPacket)
    assert packet.header.flag == 9
    assert packet.media_format == 21
    assert packet.payload == b"audio"


def test_reject_truncated_packet() -> None:
    with pytest.raises(PacketError, match="truncated packet"):
        parse_packet(b"\x68\x10\x81\x00", udp=False)


def test_reject_trailing_data_in_exact_mode() -> None:
    with pytest.raises(PacketError, match="trailing data"):
        parse_packet(b"\x38\x00extra", udp=False)


def test_iter_tcp_packets_preserves_incomplete_tail() -> None:
    first = b"\x38\x00"
    second_body = b"\x00\x01\x00payload"
    second = b"\x48" + encode_varint(len(second_body)) + second_body
    packets, remainder = iter_tcp_packets(first + second[:-2])
    assert len(packets) == 1
    assert packets[0].header.message_type == 3
    assert remainder == second[:-2]


def test_key_derivation_uses_ascii_hex_digest() -> None:
    rpc = derive_rpc_key("test-prefix", sequence=2, command_id=601, rpc_type=1)
    av = derive_av_key("test-prefix", sequence=3, timestamp=4, channel=0)
    assert rpc == b"e7cc6979db4a585c4621be41858b5f09"
    assert av == b"5151ec24d5a7a0706ccaa81fde9ced63"
