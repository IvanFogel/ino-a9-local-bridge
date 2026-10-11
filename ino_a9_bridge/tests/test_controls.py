from datetime import time

import pytest

from wificam_bridge.commands import (
    build_intrusion_payload,
    build_led_payload,
    build_motion_payload,
    build_night_payload,
    build_flip_payload,
    build_video_quality_payload,
)
from wificam_bridge.controls import IntrusionSchedule


@pytest.mark.parametrize(
    ("builder", "value", "expected"),
    [
        (build_led_payload, True, b"\x10\x01"),
        (build_led_payload, False, b"\x10\x02"),
        (build_night_payload, "enabled", b"\x10\x01"),
        (build_night_payload, "disabled", b"\x10\x02"),
        (build_night_payload, "automatic", b"\x10\x03"),
        (build_flip_payload, "upright", b"\x10\x01"),
        (build_flip_payload, "horizontal", b"\x10\x02"),
        (build_flip_payload, "vertical", b"\x10\x03"),
        (build_flip_payload, "rotate_180", b"\x10\x04"),
        (build_video_quality_payload, "sd", b"\x10\x05"),
        (build_video_quality_payload, "hd", b"\x10\x0a"),
        (build_video_quality_payload, "uhd", b"\x10\x0f"),
        (build_motion_payload, "low", b"\x10\x01"),
        (build_motion_payload, "medium", b"\x10\x02"),
        (build_motion_payload, "high", b"\x10\x03"),
        (build_motion_payload, "closed", b""),
    ],
)
def test_control_values_have_observed_wire_mappings(builder, value, expected) -> None:
    assert builder(value) == expected


def test_intrusion_schedule_encodes_days_and_minute_range() -> None:
    schedule = IntrusionSchedule(days=(0, 6), start=time(8, 0), end=time(17, 0))

    assert build_intrusion_payload(True, schedule) == bytes.fromhex(
        "10011a10120200061a080880e1011090de032001"
    )


def test_intrusion_schedule_omits_midnight_start_default() -> None:
    schedule = IntrusionSchedule(days=(0,), start=time(0, 0), end=time(0, 1))

    assert build_intrusion_payload(False, schedule) == bytes.fromhex("1a091201001a02103c2001")


@pytest.mark.parametrize(
    "schedule",
    [
        {"days": [], "start": time(8, 0), "end": time(9, 0)},
        {"days": [0, 0], "start": time(8, 0), "end": time(9, 0)},
        {"days": [7], "start": time(8, 0), "end": time(9, 0)},
        {"days": [0], "start": time(9, 0), "end": time(8, 0)},
        {"days": [0], "start": time(8, 0, 1), "end": time(9, 0)},
    ],
)
def test_intrusion_schedule_rejects_invalid_or_crossing_intervals(schedule) -> None:
    with pytest.raises((TypeError, ValueError)):
        IntrusionSchedule(**schedule)
