"""Unit tests for the safety-profile parsing, library loading and checks."""

from __future__ import annotations

import json

import pytest

from rs3005p_mcp.safety import (
    SafetyProfile,
    load_profiles,
    select_profile,
)


def make(**overrides) -> dict:
    base = {
        "device": "24 V sensor",
        "voltage": {"nominal": 24.0, "tolerance": 0.5},
        "current": {"max": 0.5, "nominal": 0.2},
        "power": {"max": 12.0},
        "max_voltage_step": 2.0,
    }
    base.update(overrides)
    return base


def test_nominal_tolerance_bounds():
    p = SafetyProfile.from_dict(make(), name="24v")
    # tolerance sets the ceiling + nominal; the floor stays at 0 V
    assert p.voltage_min == pytest.approx(0.0)
    assert p.voltage_max == pytest.approx(24.5)
    assert p.nominal_voltage == 24.0
    assert p.current_max == 0.5
    assert p.power_max == 12.0
    assert p.max_voltage_step == 2.0


def test_explicit_min_max_bounds():
    p = SafetyProfile.from_dict(
        {"voltage": {"min": 1.0, "max": 5.25}, "current": {"max": 1.0}}, name="5v"
    )
    assert p.voltage_min == 1.0
    assert p.voltage_max == 5.25
    assert p.power_max is None
    assert p.output_allowed is True


def test_tolerance_clamps_min_to_zero():
    p = SafetyProfile.from_dict(
        {"voltage": {"nominal": 0.3, "tolerance": 0.5}, "current": {"max": 1.0}},
        name="x",
    )
    assert p.voltage_min == 0.0


@pytest.mark.parametrize(
    "bad",
    [
        {"current": {"max": 1.0}},  # no voltage
        {"voltage": {"min": 0}, "current": {"max": 1.0}},  # voltage no max/nominal
        {"voltage": {"max": 5.0}},  # no current
        {"voltage": {"max": 5.0}, "current": {}},  # current no max
    ],
)
def test_invalid_profiles_raise(bad):
    with pytest.raises(ValueError):
        SafetyProfile.from_dict(bad, name="bad")


def test_voltage_checks():
    p = SafetyProfile.from_dict(make(), name="24v")
    p.check_voltage(0.0)   # floor: ramping up / off always allowed
    p.check_voltage(23.0)  # below nominal is fine (under-voltage is benign)
    p.check_voltage(24.5)  # ceiling boundary OK
    with pytest.raises(ValueError):
        p.check_voltage(25.0)  # over the ceiling -> rejected
    with pytest.raises(ValueError):
        p.check_voltage(-1.0)


def test_current_and_power_checks():
    p = SafetyProfile.from_dict(make(), name="24v")
    p.check_current(0.5)
    with pytest.raises(ValueError):
        p.check_current(0.6)
    p.check_power(24.0, 0.5)  # 12 W exactly OK
    with pytest.raises(ValueError):
        p.check_power(24.0, 0.6)  # 14.4 W


def test_step_and_output_checks():
    p = SafetyProfile.from_dict(make(), name="24v")
    p.check_step(22.0, 24.0)  # 2 V step OK
    with pytest.raises(ValueError):
        p.check_step(20.0, 24.0)  # 4 V step too big

    blocked = SafetyProfile.from_dict(make(output_allowed=False), name="x")
    with pytest.raises(ValueError):
        blocked.check_output_allowed()


def test_load_keyed_library(tmp_path):
    path = tmp_path / "devs.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "devices": {
                    "a": {"voltage": {"max": 5.0}, "current": {"max": 1.0}},
                    "b": {"voltage": {"max": 12.0}, "current": {"max": 2.0}},
                },
            }
        )
    )
    profiles = load_profiles(str(path))
    assert set(profiles) == {"a", "b"}
    assert profiles["b"].voltage_max == 12.0


def test_load_array_library(tmp_path):
    path = tmp_path / "devs.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "devices": [
                    {"name": "a", "voltage": {"max": 5.0}, "current": {"max": 1.0}},
                    {"name": "b", "voltage": {"max": 9.0}, "current": {"max": 2.0}},
                ],
            }
        )
    )
    profiles = load_profiles(str(path))
    assert set(profiles) == {"a", "b"}


def test_load_bare_single(tmp_path):
    path = tmp_path / "one.json"
    path.write_text(
        json.dumps({"device": "solo", "voltage": {"max": 5.0}, "current": {"max": 1.0}})
    )
    profiles = load_profiles(str(path))
    assert list(profiles) == ["solo"]


def test_load_top_level_array(tmp_path):
    path = tmp_path / "arr.json"
    path.write_text(
        json.dumps([{"name": "a", "voltage": {"max": 5.0}, "current": {"max": 1.0}}])
    )
    assert list(load_profiles(str(path))) == ["a"]


def test_unsupported_schema_version(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": "9.9", "devices": {}}))
    with pytest.raises(ValueError):
        load_profiles(str(path))


def test_select_profile():
    profiles = {
        "a": SafetyProfile.from_dict({"voltage": {"max": 5.0}, "current": {"max": 1.0}}, name="a"),
        "b": SafetyProfile.from_dict({"voltage": {"max": 9.0}, "current": {"max": 1.0}}, name="b"),
    }
    assert select_profile(profiles, "b").name == "b"
    with pytest.raises(ValueError):
        select_profile(profiles, "missing")
    with pytest.raises(ValueError):
        select_profile(profiles, None)  # ambiguous -> must name device

    single = {"a": profiles["a"]}
    assert select_profile(single, None).name == "a"  # sole device auto-selected
