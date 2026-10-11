"""Connection diagnostics must survive the failures they describe."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ino_a9.const import DOMAIN
from custom_components.ino_a9.coordinator import InoA9Coordinator
from custom_components.ino_a9.sensor import InoA9ConnectionDiagnostics


def make_sensor(hass, name="front"):
    coordinator = InoA9Coordinator(hass, AsyncMock())
    coordinator.data = {
        name: {
            "id": name,
            "connected": False,
            "media": {"error": "TimeoutError: timed out"},
        }
    }
    coordinator.last_update_success = True
    sensor = InoA9ConnectionDiagnostics(
        coordinator, MockConfigEntry(domain=DOMAIN), name
    )
    return coordinator, sensor


@pytest.mark.asyncio
async def test_offline_errors_deduplicate_and_survive_recovery(hass):
    coordinator, sensor = make_sensor(hass)
    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
        sensor._handle_coordinator_update()
        assert sensor.available
        assert sensor.native_value == "disconnected"
        assert len(sensor.extra_state_attributes["error_log"]) == 1
        coordinator.data["front"]["connected"] = True
        sensor._handle_coordinator_update()
        assert sensor.native_value == "connected"
        assert sensor.extra_state_attributes["error"] is None
        assert len(sensor.extra_state_attributes["error_log"]) == 1
        coordinator.data["front"]["connected"] = False
        sensor._handle_coordinator_update()
        assert len(sensor.extra_state_attributes["error_log"]) == 2
        coordinator.last_update_success = False
        sensor._handle_coordinator_update()
        assert not sensor.available
        assert len(sensor.extra_state_attributes["error_log"]) == 2


@pytest.mark.asyncio
async def test_error_history_is_bounded_separate_and_redacted(hass):
    coordinator, sensor = make_sensor(hass)
    _, other = make_sensor(hass, "back")
    with patch.object(sensor, "async_write_ha_state"):
        for i in range(12):
            coordinator.data["front"]["media"]["error"] = f"Error {i}"
            sensor._handle_coordinator_update()
        history = sensor.extra_state_attributes["error_log"]
        assert len(history) == 10
        assert history[0]["message"] == "Error 2"
        assert other.extra_state_attributes["error_log"] == []
        coordinator.data["front"]["media"]["error"] = (
            "Authorization: Bearer private-value"
        )
        sensor._handle_coordinator_update()
        assert "private-value" not in str(sensor.extra_state_attributes)


@pytest.mark.asyncio
async def test_restored_errors_preserve_history_without_duplicate(hass):
    _, sensor = make_sensor(hass)
    sensor._restore_errors(
        State(
            "sensor.front",
            "disconnected",
            {
                "error": "TimeoutError: timed out",
                "error_log": [
                    None,
                    {"message": "bad", "timestamp": "invalid"},
                    {
                        "message": "TimeoutError: timed out",
                        "timestamp": "2026-10-11T11:00:00+00:00",
                    },
                ],
            },
        )
    )
    sensor._record_error()
    assert sensor.extra_state_attributes["error_log"] == [
        {"message": "TimeoutError: timed out", "timestamp": "2026-10-11T11:00:00+00:00"}
    ]
