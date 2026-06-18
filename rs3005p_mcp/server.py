"""MCP tool surface for the RS-3005P / RS-6005P power supply.

The server owns a single active connection (these are single-output bench
units; one agent drives one supply). Tools are thin wrappers that translate to
:class:`PowerSupply` calls and return JSON-friendly dicts, so all real logic and
validation lives in the testable lower layers.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .device import PowerSupply
from .models import DEFAULT_MODEL, MODELS
from .transport import open_serial

mcp = FastMCP("rs3005p")

# Single active connection, set by `connect` and cleared by `disconnect`.
_device: PowerSupply | None = None


def _require_device() -> PowerSupply:
    if _device is None:
        raise RuntimeError(
            "Not connected. Call `connect` with the serial port first "
            "(use `list_serial_ports` to discover it)."
        )
    return _device


@mcp.tool()
def list_serial_ports() -> list[dict]:
    """List serial ports available on this machine.

    Use this to find the port the power supply is on (it enumerates as a USB
    virtual COM port, e.g. ``COM4`` on Windows or ``/dev/ttyUSB0`` on Linux).
    """
    from serial.tools import list_ports

    return [
        {"port": p.device, "description": p.description, "hwid": p.hwid}
        for p in list_ports.comports()
    ]


@mcp.tool()
def connect(port: str, model: str = DEFAULT_MODEL, baudrate: int = 9600) -> dict:
    """Open a serial connection to the power supply and verify it responds.

    Args:
        port: Serial port name, e.g. ``COM4`` or ``/dev/ttyUSB0``.
        model: One of the supported models (sets the voltage/current limits).
            Defaults to RS-3005P (0-30 V, 0-5 A).
        baudrate: Serial baud rate; the manual specifies 9600.

    Returns the device identification string and the active output limits.
    """
    global _device
    if model not in MODELS:
        raise ValueError(
            f"Unknown model {model!r}; supported: {sorted(MODELS)}."
        )
    if _device is not None:
        _device.close()
        _device = None

    transport = open_serial(port, baudrate=baudrate)
    device = PowerSupply(transport, MODELS[model])
    identification = device.identify()
    _device = device
    return {
        "connected": True,
        "port": port,
        "model": model,
        "identification": identification,
        "max_voltage": device.model.max_voltage,
        "max_current": device.model.max_current,
    }


@mcp.tool()
def disconnect() -> dict:
    """Close the serial connection to the power supply."""
    global _device
    if _device is not None:
        _device.close()
        _device = None
    return {"connected": False}


@mcp.tool()
def get_identification() -> str:
    """Return the instrument identification string (``*IDN?``)."""
    return _require_device().identify()


@mcp.tool()
def set_voltage(volts: float) -> dict:
    """Set the output voltage setpoint, in volts.

    Rejected if outside the connected model's range (e.g. 0-30 V on RS-3005P).
    """
    device = _require_device()
    device.set_voltage(volts)
    return {"voltage_setpoint": device.get_voltage_setpoint()}


@mcp.tool()
def set_current(amps: float) -> dict:
    """Set the output current limit, in amps (0-5 A).

    In constant-current operation this is the current the supply holds the
    output to; rejected if outside the model's range.
    """
    device = _require_device()
    device.set_current(amps)
    return {"current_setpoint": device.get_current_setpoint()}


@mcp.tool()
def get_setpoints() -> dict:
    """Return the configured voltage and current setpoints."""
    device = _require_device()
    return {
        "voltage_setpoint": device.get_voltage_setpoint(),
        "current_setpoint": device.get_current_setpoint(),
    }


@mcp.tool()
def measure() -> dict:
    """Read the actual output voltage (V) and current (A) at the terminals."""
    device = _require_device()
    return {
        "output_voltage": device.measure_voltage(),
        "output_current": device.measure_current(),
    }


@mcp.tool()
def set_output(enabled: bool) -> dict:
    """Enable (True) or disable (False) the output terminals.

    Enabling makes the terminals live at the configured setpoints.
    """
    device = _require_device()
    device.set_output(enabled)
    return {"output_enabled": device.get_status().output_enabled}


@mcp.tool()
def set_ocp(enabled: bool) -> dict:
    """Arm (True) or disarm (False) over-current protection.

    When armed, the output is cut off if the current reaches the setpoint.
    """
    device = _require_device()
    device.set_ocp(enabled)
    return {"ocp_enabled": device.get_status().ocp_enabled}


@mcp.tool()
def get_status() -> dict:
    """Return decoded device status: output state, CV/CC mode, OCP state."""
    return _require_device().get_status().as_dict()


@mcp.tool()
def get_state() -> dict:
    """Return a full snapshot: setpoints, live measurements and status."""
    return _require_device().snapshot()


@mcp.tool()
def save_settings(slot: int) -> dict:
    """Store the current panel settings into memory *slot* (1-5)."""
    _require_device().save(slot)
    return {"saved_slot": slot}


@mcp.tool()
def recall_settings(slot: int) -> dict:
    """Recall panel settings from memory *slot* (1-5)."""
    device = _require_device()
    device.recall(slot)
    return {"recalled_slot": slot}
