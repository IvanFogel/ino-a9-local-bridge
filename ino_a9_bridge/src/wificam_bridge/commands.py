"""Payload builders for observed, local-only INO-A9 PPRPC controls."""

from __future__ import annotations

from typing import Final

from .controls import IntrusionSchedule
from .pprpc import decode_varint, encode_varint


STATUS_LED_COMMAND: Final = 2633
NIGHT_SET_COMMAND: Final = 2635
NIGHT_GET_COMMAND: Final = 2636
FLIP_SET_COMMAND: Final = 2613
FLIP_GET_COMMAND: Final = 2649
VIDEO_QUALITY_COMMAND: Final = 2612
INTRUSION_COMMAND: Final = 2639
MOTION_COMMAND: Final = 2661
REBOOT_COMMAND: Final = 2647

NIGHT_VALUES: Final = {"enabled": 1, "disabled": 2, "automatic": 3}
FLIP_VALUES: Final = {"upright": 1, "horizontal": 2, "vertical": 3, "rotate_180": 4}
VIDEO_QUALITY_VALUES: Final = {"sd": 5, "hd": 10, "uhd": 15}
MOTION_VALUES: Final = {"low": 1, "medium": 2, "high": 3, "closed": 0}


def _value_payload(value: int) -> bytes:
    return encode_varint(2 << 3) + encode_varint(value)


def _enum_payload(value: object, values: dict[str, int], label: str) -> bytes:
    if not isinstance(value, str) or value not in values:
        raise ValueError(f"invalid {label}")
    return _value_payload(values[value])


def build_led_payload(enabled: bool) -> bytes:
    if not isinstance(enabled, bool):
        raise ValueError("led value must be a boolean")
    return _value_payload(1 if enabled else 2)


def build_night_payload(value: object) -> bytes:
    return _enum_payload(value, NIGHT_VALUES, "night vision mode")


def build_flip_payload(value: object) -> bytes:
    return _enum_payload(value, FLIP_VALUES, "flip mode")


def build_video_quality_payload(value: object) -> bytes:
    return _enum_payload(value, VIDEO_QUALITY_VALUES, "video quality")


def build_motion_payload(value: object) -> bytes:
    if not isinstance(value, str) or value not in MOTION_VALUES:
        raise ValueError("invalid motion sensitivity")
    wire_value = MOTION_VALUES[value]
    return b"" if wire_value == 0 else _value_payload(wire_value)


def build_intrusion_payload(enabled: bool, schedule: IntrusionSchedule) -> bytes:
    if not isinstance(enabled, bool):
        raise ValueError("intrusion enabled must be a boolean")
    if not isinstance(schedule, IntrusionSchedule):
        raise TypeError("schedule must be an IntrusionSchedule")
    start_seconds = _seconds(schedule.start)
    time_range = _value_field(2, _seconds(schedule.end))
    if start_seconds:
        time_range = _value_field(1, start_seconds) + time_range
    nested = _bytes_field(2, bytes(schedule.days)) + _bytes_field(3, time_range) + _value_field(4, 1)
    payload = _bytes_field(3, nested)
    return _value_field(2, 1) + payload if enabled else payload


def read_response_value(payload: bytes) -> int | None:
    """Return protobuf field 1 from a getter response, if present."""
    offset = 0
    while offset < len(payload):
        tag, offset = decode_varint(payload, offset)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, offset = decode_varint(payload, offset)
            if number == 1:
                return value
        elif wire_type == 1:
            offset += 8
        elif wire_type == 2:
            length, offset = decode_varint(payload, offset)
            offset += length
        elif wire_type == 5:
            offset += 4
        else:
            raise ValueError("unsupported protobuf wire type")
        if offset > len(payload):
            raise ValueError("truncated protobuf field")
    return None


def _value_field(number: int, value: int) -> bytes:
    return encode_varint(number << 3) + encode_varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return encode_varint((number << 3) | 2) + encode_varint(len(value)) + value


def _seconds(value: object) -> int:
    if not hasattr(value, "hour"):
        raise TypeError("schedule value must be a time")
    return value.hour * 3600 + value.minute * 60
