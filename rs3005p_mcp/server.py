"""MCP tool surface for the RS-3005P / RS-6005P power supply.

The server owns a single active connection (these are single-output bench
units; one agent drives one supply). Tools are thin wrappers that translate to
:class:`PowerSupply` calls and return JSON-friendly dicts, so all real logic and
validation lives in the testable lower layers.

Safety: an operator may attach a device-profile library by setting
``RS3005P_PROFILE`` (a file path) and ``RS3005P_DEVICE`` (which device is wired
up) before launching the server. The selected profile clamps what the agent can
do; no tool here can create, change or switch it -- selection happens only at
startup from the environment.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .device import PowerSupply
from .models import DEFAULT_MODEL, MODELS
from .safety import SafetyProfile, load_profiles, select_profile
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


def _active_profile() -> SafetyProfile | None:
    """Resolve the operator-configured safety profile from the environment.

    Reads the file/device named by ``RS3005P_PROFILE`` / ``RS3005P_DEVICE``.
    Returns ``None`` (fail-loud, hardware-limited only) when no profile is set.
    """
    path = os.environ.get("RS3005P_PROFILE")
    if not path:
        return None
    profiles = load_profiles(path)
    return select_profile(profiles, os.environ.get("RS3005P_DEVICE"))


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
def get_safety_profile() -> dict:
    """Return the active safety envelope (read-only) for the attached device.

    The envelope is fixed by the operator at startup and cannot be changed from
    here. If no profile is configured, the supply is limited only by hardware
    (30 V / 5 A) and you should treat connected devices with caution.
    """
    profile = _active_profile()
    if profile is None:
        return {"profile_active": False, "note": "No DUT profile; hardware limits only."}
    return {"profile_active": True, **profile.as_dict()}


@mcp.tool()
def connect(port: str, model: str = DEFAULT_MODEL, baudrate: int = 9600) -> dict:
    """Open a serial connection to the power supply and verify it responds.

    Args:
        port: Serial port name, e.g. ``COM4`` or ``/dev/ttyUSB0``.
        model: One of the supported models (sets the hardware limits).
            Defaults to RS-3005P (0-30 V, 0-5 A).
        baudrate: Serial baud rate; the manual specifies 9600.

    Applies the operator's active safety profile (if any). If the supply is
    found already outputting outside the safe envelope, the output is forced off
    and a warning is returned.
    """
    global _device
    if model not in MODELS:
        raise ValueError(f"Unknown model {model!r}; supported: {sorted(MODELS)}.")
    if _device is not None:
        _device.close()
        _device = None

    profile = _active_profile()
    transport = open_serial(port, baudrate=baudrate)
    device = PowerSupply(transport, MODELS[model], profile=profile)
    identification = device.identify()
    warnings = device.enforce_safe_on_connect()
    _device = device
    return {
        "connected": True,
        "port": port,
        "model": model,
        "identification": identification,
        "max_voltage": device.model.max_voltage,
        "max_current": device.model.max_current,
        "safety_profile": profile.name if profile else None,
        "safety_note": (
            f"Envelope enforced for '{profile.device}'."
            if profile
            else "No DUT profile active -- hardware limits only (30 V/5 A)."
        ),
        "warnings": warnings,
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

    Rejected if outside the hardware range or the active device's safe envelope.
    """
    device = _require_device()
    device.set_voltage(volts)
    return {"voltage_setpoint": device.get_voltage_setpoint()}


@mcp.tool()
def set_current(amps: float) -> dict:
    """Set the output current limit, in amps.

    Rejected if outside the hardware range or the active device's safe envelope.
    """
    device = _require_device()
    device.set_current(amps)
    return {"current_setpoint": device.get_current_setpoint()}


@mcp.tool()
def ramp_voltage(target_volts: float) -> dict:
    """Ramp the voltage to *target_volts*, respecting the profile's slew limit.

    Use this instead of `set_voltage` to reach a value more than one step away
    when a `max_voltage_step` is configured.
    """
    device = _require_device()
    device.ramp_voltage(target_volts)
    return {"voltage_setpoint": device.get_voltage_setpoint()}


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

    Enabling is refused if the profile forbids output or the present setpoints
    are outside the safe envelope. Disabling is always allowed.
    """
    device = _require_device()
    device.set_output(enabled)
    return {"output_enabled": device.get_status().output_enabled}


@mcp.tool()
def power_up() -> dict:
    """Bring the attached device to its profile's nominal operating point.

    Sets the current limit to the profile's nominal (or max) current, ramps the
    voltage to the profile's nominal voltage within the slew limit, then enables
    the output. Requires an active profile that defines a nominal voltage and
    allows output.
    """
    device = _require_device()
    profile = device.profile
    if profile is None:
        raise RuntimeError("power_up requires an active safety profile.")
    if profile.nominal_voltage is None:
        raise RuntimeError(
            f"Profile '{profile.device}' defines no nominal voltage to power up to."
        )
    profile.check_output_allowed()
    target_current = (
        profile.nominal_current
        if profile.nominal_current is not None
        else profile.current_max
    )
    device.set_current(target_current)
    device.ramp_voltage(profile.nominal_voltage)
    device.set_output(True)
    return device.snapshot()


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
    """Recall panel settings from memory *slot* (1-5).

    If a safety profile is active and the recalled preset is outside the
    envelope, the output is forced off and this raises.
    """
    device = _require_device()
    device.recall(slot)
    return {"recalled_slot": slot}
