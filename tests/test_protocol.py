"""Unit tests for the pure encode/decode protocol layer."""

from __future__ import annotations

import pytest

from rs3005p_mcp import protocol
from rs3005p_mcp.models import MODELS


def test_identify_command():
    assert protocol.cmd_identify() == b"*IDN?"


def test_setpoint_query_commands():
    assert protocol.cmd_query_voltage_setpoint() == b"VSET1?"
    assert protocol.cmd_query_current_setpoint() == b"ISET1?"
    assert protocol.cmd_query_output_voltage() == b"VOUT1?"
    assert protocol.cmd_query_output_current() == b"IOUT1?"
    assert protocol.cmd_query_status() == b"STATUS?"


def test_set_commands_embed_formatted_field():
    model = MODELS["RS-3005P"]
    assert protocol.cmd_set_voltage(model.format_voltage(20.5)) == b"VSET1:20.50"
    assert protocol.cmd_set_voltage(model.format_voltage(5.0)) == b"VSET1:05.00"
    assert protocol.cmd_set_current(model.format_current(2.225)) == b"ISET1:2.225"
    assert protocol.cmd_set_current(model.format_current(0.5)) == b"ISET1:0.500"


def test_output_and_ocp_commands():
    assert protocol.cmd_set_output(True) == b"OUT1"
    assert protocol.cmd_set_output(False) == b"OUT0"
    assert protocol.cmd_set_ocp(True) == b"OCP1"
    assert protocol.cmd_set_ocp(False) == b"OCP0"


def test_memory_commands():
    assert protocol.cmd_save(1) == b"SAV1"
    assert protocol.cmd_recall(5) == b"RCL5"


@pytest.mark.parametrize("slot", [0, 6, -1, 1.5, "1"])
def test_memory_slot_validation(slot):
    with pytest.raises(ValueError):
        protocol.cmd_save(slot)
    with pytest.raises(ValueError):
        protocol.cmd_recall(slot)


def test_channel_validation():
    with pytest.raises(ValueError):
        protocol.cmd_query_voltage_setpoint(channel=2)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (b"30.00", 30.0),
        (b"05.00", 5.0),
        (b"5.000", 5.0),
        (b"  12.34 ", 12.34),
        (b"0.500\x00", 0.5),  # trailing junk tolerated
    ],
)
def test_parse_float(raw, expected):
    assert protocol.parse_float(raw) == pytest.approx(expected)


def test_parse_float_rejects_non_numeric():
    with pytest.raises(ValueError):
        protocol.parse_float(b"ERR")


def test_decode_status_bits():
    # bit0 = CV, bit5 = OCP, bit6 = output
    status = protocol.decode_status(bytes([0b01000001]))
    assert status.output_enabled is True
    assert status.constant_voltage is True
    assert status.constant_current is False
    assert status.ocp_enabled is False
    assert status.mode == "CV"

    status = protocol.decode_status(bytes([0b00100000]))
    assert status.output_enabled is False
    assert status.constant_voltage is False
    assert status.constant_current is True
    assert status.ocp_enabled is True
    assert status.mode == "CC"


def test_decode_status_as_dict():
    data = protocol.decode_status(bytes([0b01000001])).as_dict()
    assert data["mode"] == "CV"
    assert data["output_enabled"] is True
    assert data["raw"] == 0b01000001


def test_decode_status_rejects_empty():
    with pytest.raises(ValueError):
        protocol.decode_status(b"")
