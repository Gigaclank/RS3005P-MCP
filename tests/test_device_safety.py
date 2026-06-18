"""Device-layer tests for safety-profile enforcement against the fake device."""

from __future__ import annotations

import pytest

from rs3005p_mcp.device import PowerSupply
from rs3005p_mcp.models import MODELS
from rs3005p_mcp.safety import SafetyProfile
from rs3005p_mcp.transport import SerialTransport
from tests.conftest import FakeKorad


def build(profile_dict, name="dut"):
    fake = FakeKorad()
    dev = PowerSupply(
        SerialTransport(fake, command_delay=0.0),
        MODELS["RS-3005P"],
        profile=SafetyProfile.from_dict(profile_dict, name=name),
    )
    return dev, fake


TIGHT = {  # 24 V +/- 0.5, <= 0.5 A, <= 12 W, 2 V slew
    "device": "24 V sensor",
    "voltage": {"nominal": 24.0, "tolerance": 0.5},
    "current": {"max": 0.5, "nominal": 0.2},
    "power": {"max": 12.0},
    "max_voltage_step": 2.0,
}


def test_voltage_envelope_enforced():
    dev, fake = build({"voltage": {"min": 0.0, "max": 5.0}, "current": {"max": 1.0}})
    dev.set_voltage(5.0)
    assert fake.vset == pytest.approx(5.0)
    with pytest.raises(ValueError):
        dev.set_voltage(6.0)


def test_current_envelope_enforced():
    dev, fake = build({"voltage": {"min": 0.0, "max": 5.0}, "current": {"max": 1.0}})
    dev.set_current(1.0)
    with pytest.raises(ValueError):
        dev.set_current(1.5)


def test_power_ceiling_enforced():
    dev, fake = build(
        {"voltage": {"min": 0.0, "max": 30.0}, "current": {"max": 5.0}, "power": {"max": 10.0}}
    )
    dev.set_voltage(5.0)
    dev.set_current(2.0)  # 10 W exactly
    with pytest.raises(ValueError):
        dev.set_current(2.5)  # 12.5 W
    with pytest.raises(ValueError):
        dev.set_voltage(6.0)  # 6 * 2 = 12 W


def test_slew_limit_and_ramp():
    dev, fake = build(
        {"voltage": {"min": 0.0, "max": 30.0}, "current": {"max": 5.0}, "max_voltage_step": 2.0}
    )
    dev.set_voltage(2.0)  # one step from 0 OK
    with pytest.raises(ValueError):
        dev.set_voltage(10.0)  # jump too big
    dev.ramp_voltage(6.0, step_dwell=0.0)
    assert fake.vset == pytest.approx(6.0)


def test_output_gating_disallowed():
    dev, fake = build({"voltage": {"max": 5.0}, "current": {"max": 1.0}, "output_allowed": False})
    with pytest.raises(ValueError):
        dev.set_output(True)
    assert fake.output is False
    dev.set_output(False)  # disabling always allowed


def test_output_gating_requires_safe_setpoints():
    # profile without slew limit so we can set setpoints directly
    dev, fake = build(
        {
            "device": "24 V sensor",
            "voltage": {"nominal": 24.0, "tolerance": 0.5},
            "current": {"max": 0.5},
        }
    )
    # supply left with setpoint above the 24.5 V ceiling -> enabling refused
    fake.vset = 30.0
    with pytest.raises(ValueError):
        dev.set_output(True)
    assert fake.output is False
    # bring setpoints into the envelope, then it is allowed
    dev.set_voltage(24.0)
    dev.set_current(0.2)
    dev.set_output(True)
    assert fake.output is True


def test_recall_unsafe_forces_output_off():
    dev, fake = build(TIGHT)
    fake.output = True
    fake._memory[1] = (28.0, 0.3)  # 28 V is above the 24.5 V ceiling
    with pytest.raises(ValueError):
        dev.recall(1)
    assert fake.output is False


def test_enforce_safe_on_connect():
    dev, fake = build(TIGHT)
    fake.vset = 28.0  # above the 24.5 V ceiling
    fake.output = True
    warnings = dev.enforce_safe_on_connect()
    assert fake.output is False
    assert warnings and "forced OFF" in warnings[0]


def test_no_profile_is_unrestricted_within_hardware():
    fake = FakeKorad()
    dev = PowerSupply(SerialTransport(fake, command_delay=0.0), MODELS["RS-3005P"])
    dev.set_voltage(30.0)  # full hardware range allowed, no profile
    assert fake.vset == pytest.approx(30.0)
