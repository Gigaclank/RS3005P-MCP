"""Versioned hardware definitions for the RS-3000/6000 series.

Each :class:`PowerSupplyModel` captures everything that differs between
variants: the output envelope (max voltage / current) and the exact ASCII
number format the firmware expects on the wire. Keeping these as explicit data
(rather than scattering magic numbers through the code) means adding a new
variant is a single table entry, and the wire format is documented in one place.

Values and limits are taken from the RS3000/6000-Series User Manual
(Specifications table) and the "RS Series Remote Control Syntax V2.0" section.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PowerSupplyModel:
    """Immutable description of a single power-supply variant.

    Attributes:
        name: Canonical model name, e.g. ``"RS-3005P"``.
        max_voltage: Highest settable output voltage, in volts.
        max_current: Highest settable output current, in amps.
        voltage_resolution: Smallest voltage step the panel resolves, in volts.
        current_resolution: Smallest current step the panel resolves, in amps.
        voltage_format: ``str.format`` spec used to encode a voltage setpoint
            for the firmware (e.g. ``"{:05.2f}"`` -> ``"05.00"``).
        current_format: ``str.format`` spec used to encode a current setpoint
            (e.g. ``"{:05.3f}"`` -> ``"0.500"``).
    """

    name: str
    max_voltage: float
    max_current: float
    voltage_resolution: float = 0.01
    current_resolution: float = 0.001
    voltage_format: str = "{:05.2f}"
    current_format: str = "{:05.3f}"

    def format_voltage(self, volts: float) -> str:
        """Render *volts* as the firmware-expected ASCII field."""
        return self.voltage_format.format(volts)

    def format_current(self, amps: float) -> str:
        """Render *amps* as the firmware-expected ASCII field."""
        return self.current_format.format(amps)


# Registry of supported models. The "P" suffix variants (RS-3005P / RS-6005P)
# are the ones with the RS232 + USB remote-control interface; the "D" variants
# have no remote interface and so cannot be driven by this server.
MODELS: dict[str, PowerSupplyModel] = {
    "RS-3005P": PowerSupplyModel(name="RS-3005P", max_voltage=30.0, max_current=5.0),
    "RS-6005P": PowerSupplyModel(name="RS-6005P", max_voltage=60.0, max_current=5.0),
}

DEFAULT_MODEL = "RS-3005P"
