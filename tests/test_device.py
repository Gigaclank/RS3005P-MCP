"""End-to-end tests of the device layer driving the fake firmware."""

from __future__ import annotations

import pytest

from rs3005p_mcp.device import PowerSupply
from tests.conftest import FakeKorad


def test_identify(device: PowerSupply):
    assert device.identify() == "KORAD RS3005P V2.0"


def test_set_and_read_voltage_setpoint(device: PowerSupply, fake: FakeKorad):
    device.set_voltage(12.34)
    assert fake.written[-1] == b"VSET1:12.34"
    assert device.get_voltage_setpoint() == pytest.approx(12.34)


def test_set_and_read_current_setpoint(device: PowerSupply, fake: FakeKorad):
    device.set_current(2.225)
    assert fake.written[-1] == b"ISET1:2.225"
    assert device.get_current_setpoint() == pytest.approx(2.225)


def test_voltage_out_of_range_rejected(device: PowerSupply, fake: FakeKorad):
    with pytest.raises(ValueError):
        device.set_voltage(31.0)
    with pytest.raises(ValueError):
        device.set_voltage(-1.0)
    # Nothing should have been sent to the device.
    assert fake.written == []


def test_current_out_of_range_rejected(device: PowerSupply, fake: FakeKorad):
    with pytest.raises(ValueError):
        device.set_current(5.1)
    assert fake.written == []


def test_measurements_track_output_state(device: PowerSupply):
    device.set_voltage(10.0)
    device.set_current(1.0)
    # Output off -> terminals read zero.
    assert device.measure_voltage() == pytest.approx(0.0)
    assert device.measure_current() == pytest.approx(0.0)
    # Output on -> terminals read the setpoints (per the emulator).
    device.set_output(True)
    assert device.measure_voltage() == pytest.approx(10.0)
    assert device.measure_current() == pytest.approx(1.0)


def test_output_and_status(device: PowerSupply):
    device.set_output(True)
    status = device.get_status()
    assert status.output_enabled is True
    assert status.mode == "CV"
    device.set_output(False)
    assert device.get_status().output_enabled is False


def test_ocp_status(device: PowerSupply):
    device.set_ocp(True)
    assert device.get_status().ocp_enabled is True
    device.set_ocp(False)
    assert device.get_status().ocp_enabled is False


def test_save_and_recall(device: PowerSupply):
    device.set_voltage(15.0)
    device.set_current(2.0)
    device.save(3)
    device.set_voltage(1.0)
    device.set_current(0.1)
    device.recall(3)
    assert device.get_voltage_setpoint() == pytest.approx(15.0)
    assert device.get_current_setpoint() == pytest.approx(2.0)


def test_snapshot(device: PowerSupply):
    device.set_voltage(9.0)
    device.set_current(1.5)
    device.set_output(True)
    snap = device.snapshot()
    assert snap["model"] == "RS-3005P"
    assert snap["voltage_setpoint"] == pytest.approx(9.0)
    assert snap["current_setpoint"] == pytest.approx(1.5)
    assert snap["output_voltage"] == pytest.approx(9.0)
    assert snap["output_current"] == pytest.approx(1.5)
    assert snap["output_enabled"] is True
    assert snap["mode"] == "CV"
    assert snap["ocp_enabled"] is False


def test_close(device: PowerSupply, fake: FakeKorad):
    device.close()
    assert fake.is_open is False
