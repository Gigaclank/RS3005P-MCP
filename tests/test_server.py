"""Tests for the MCP tool wrappers.

The `@mcp.tool()` decorator returns the original function unchanged, so each
tool is callable directly. We inject a fake-backed device into the module-level
connection slot to drive them without hardware.
"""

from __future__ import annotations

import pytest

from rs3005p_mcp import server
from rs3005p_mcp.device import PowerSupply
from rs3005p_mcp.models import MODELS
from rs3005p_mcp.transport import SerialTransport
from tests.conftest import FakeKorad


@pytest.fixture
def connected(monkeypatch):
    """Install a fake-backed device as the server's active connection."""
    fake = FakeKorad()
    device = PowerSupply(SerialTransport(fake, command_delay=0.0), MODELS["RS-3005P"])
    monkeypatch.setattr(server, "_device", device)
    return fake


def test_tools_require_connection(monkeypatch):
    monkeypatch.setattr(server, "_device", None)
    with pytest.raises(RuntimeError):
        server.get_identification()
    with pytest.raises(RuntimeError):
        server.set_voltage(5.0)


def test_connect_verifies_and_stores(monkeypatch):
    fake = FakeKorad()

    def fake_open_serial(port, baudrate=9600):
        return SerialTransport(fake, command_delay=0.0)

    monkeypatch.delenv("RS3005P_PROFILE", raising=False)
    monkeypatch.setattr(server, "_device", None)
    monkeypatch.setattr(server, "open_serial", fake_open_serial)

    result = server.connect("COM-TEST", model="RS-3005P")
    assert result["connected"] is True
    assert result["identification"] == "KORAD RS3005P V2.0"
    assert result["max_voltage"] == 30.0
    assert result["safety_profile"] is None
    assert server._device is not None

    # Cleanup.
    server.disconnect()
    assert server._device is None


def test_connect_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(server, "_device", None)
    with pytest.raises(ValueError):
        server.connect("COM-TEST", model="RS-9999X")


def test_set_voltage_tool(connected: FakeKorad):
    result = server.set_voltage(12.0)
    assert result["voltage_setpoint"] == pytest.approx(12.0)
    assert connected.vset == pytest.approx(12.0)


def test_set_current_tool(connected: FakeKorad):
    result = server.set_current(1.5)
    assert result["current_setpoint"] == pytest.approx(1.5)


def test_set_voltage_tool_validates(connected: FakeKorad):
    with pytest.raises(ValueError):
        server.set_voltage(99.0)


def test_output_and_status_tools(connected: FakeKorad):
    assert server.set_output(True)["output_enabled"] is True
    assert server.get_status()["output_enabled"] is True
    assert server.set_output(False)["output_enabled"] is False


def test_ocp_tool(connected: FakeKorad):
    assert server.set_ocp(True)["ocp_enabled"] is True


def test_measure_and_state_tools(connected: FakeKorad):
    server.set_voltage(8.0)
    server.set_current(1.0)
    server.set_output(True)
    measured = server.measure()
    assert measured["output_voltage"] == pytest.approx(8.0)
    state = server.get_state()
    assert state["model"] == "RS-3005P"
    assert state["output_enabled"] is True


def test_setpoints_tool(connected: FakeKorad):
    server.set_voltage(7.0)
    server.set_current(0.25)
    sp = server.get_setpoints()
    assert sp["voltage_setpoint"] == pytest.approx(7.0)
    assert sp["current_setpoint"] == pytest.approx(0.25)


def test_memory_tools(connected: FakeKorad):
    server.set_voltage(20.0)
    server.set_current(2.0)
    assert server.save_settings(2)["saved_slot"] == 2
    server.set_voltage(1.0)
    assert server.recall_settings(2)["recalled_slot"] == 2
    assert server.get_setpoints()["voltage_setpoint"] == pytest.approx(20.0)


def _write_library(tmp_path):
    import json

    path = tmp_path / "devices.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "devices": {
                    "24v-sensor": {
                        "device": "24 V sensor",
                        "voltage": {"nominal": 24.0, "tolerance": 0.5},
                        "current": {"max": 0.5, "nominal": 0.2},
                        "power": {"max": 12.0},
                        "max_voltage_step": 2.0,
                    },
                    "5v-logic": {
                        "voltage": {"min": 0.0, "max": 5.25},
                        "current": {"max": 1.0},
                    },
                },
            }
        )
    )
    return str(path)


def _connect_with_profile(monkeypatch, tmp_path, device_name):
    fake = FakeKorad()
    monkeypatch.setenv("RS3005P_PROFILE", _write_library(tmp_path))
    monkeypatch.setenv("RS3005P_DEVICE", device_name)
    monkeypatch.setattr(server, "_device", None)
    monkeypatch.setattr(
        server, "open_serial", lambda port, baudrate=9600: SerialTransport(fake, command_delay=0.0)
    )
    result = server.connect("COM-TEST")
    return fake, result


def test_connect_applies_selected_profile(monkeypatch, tmp_path):
    fake, result = _connect_with_profile(monkeypatch, tmp_path, "5v-logic")
    assert result["safety_profile"] == "5v-logic"
    # 5v-logic caps voltage at 5.25 V
    server.set_voltage(5.0)
    with pytest.raises(ValueError):
        server.set_voltage(10.0)
    server.disconnect()


def test_connect_forces_off_unsafe_output(monkeypatch, tmp_path):
    # Supply left live at 12 V, but 5v-logic envelope tops out at 5.25 V.
    fake = FakeKorad()
    fake.vset = 12.0
    fake.output = True
    monkeypatch.setenv("RS3005P_PROFILE", _write_library(tmp_path))
    monkeypatch.setenv("RS3005P_DEVICE", "5v-logic")
    monkeypatch.setattr(server, "_device", None)
    monkeypatch.setattr(
        server, "open_serial", lambda port, baudrate=9600: SerialTransport(fake, command_delay=0.0)
    )
    result = server.connect("COM-TEST")
    assert fake.output is False
    assert result["warnings"]
    server.disconnect()


def test_get_safety_profile_tool(monkeypatch, tmp_path):
    monkeypatch.delenv("RS3005P_PROFILE", raising=False)
    assert server.get_safety_profile()["profile_active"] is False
    monkeypatch.setenv("RS3005P_PROFILE", _write_library(tmp_path))
    monkeypatch.setenv("RS3005P_DEVICE", "24v-sensor")
    active = server.get_safety_profile()
    assert active["profile_active"] is True
    assert active["name"] == "24v-sensor"
    assert active["voltage_max"] == pytest.approx(24.5)


def test_power_up_tool(monkeypatch, tmp_path):
    fake, _ = _connect_with_profile(monkeypatch, tmp_path, "24v-sensor")
    snap = server.power_up()
    assert fake.output is True
    assert snap["voltage_setpoint"] == pytest.approx(24.0)
    assert snap["current_setpoint"] == pytest.approx(0.2)
    server.disconnect()


def test_list_serial_ports(monkeypatch):
    class _Port:
        device = "COM7"
        description = "USB Serial"
        hwid = "USB VID:PID=1234"

    monkeypatch.setattr(
        "serial.tools.list_ports.comports", lambda: [_Port()]
    )
    ports = server.list_serial_ports()
    assert ports == [
        {"port": "COM7", "description": "USB Serial", "hwid": "USB VID:PID=1234"}
    ]
