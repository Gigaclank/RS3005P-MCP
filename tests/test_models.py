"""Unit tests for the model definitions and value formatting."""

from __future__ import annotations

import pytest

from rs3005p_mcp.models import MODELS


def test_known_models():
    assert MODELS["RS-3005P"].max_voltage == 30.0
    assert MODELS["RS-3005P"].max_current == 5.0
    assert MODELS["RS-6005P"].max_voltage == 60.0
    assert MODELS["RS-6005P"].max_current == 5.0


@pytest.mark.parametrize(
    "volts,expected",
    [(0.0, "00.00"), (5.0, "05.00"), (12.34, "12.34"), (30.0, "30.00")],
)
def test_voltage_formatting(volts, expected):
    assert MODELS["RS-3005P"].format_voltage(volts) == expected


def test_voltage_formatting_60v_model():
    assert MODELS["RS-6005P"].format_voltage(60.0) == "60.00"


@pytest.mark.parametrize(
    "amps,expected",
    [(0.0, "0.000"), (0.5, "0.500"), (2.225, "2.225"), (5.0, "5.000")],
)
def test_current_formatting(amps, expected):
    assert MODELS["RS-3005P"].format_current(amps) == expected


def test_model_is_immutable():
    with pytest.raises(Exception):
        MODELS["RS-3005P"].max_voltage = 99  # type: ignore[misc]
