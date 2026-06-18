"""High-level instrument operations with range validation.

This is the layer an application (or the MCP server) talks to. It combines the
pure :mod:`protocol` encoders/decoders with a :class:`SerialTransport`, and adds
the safety the protocol layer deliberately omits: setpoints are validated
against the connected model's output envelope *before* anything is sent, so an
out-of-range request fails loudly instead of being silently clamped or sent to
hardware.
"""

from __future__ import annotations

from . import protocol
from .models import PowerSupplyModel
from .protocol import Status
from .transport import SerialTransport


class PowerSupply:
    """A connected RS-3005P / RS-6005P, driven over a serial transport."""

    def __init__(self, transport: SerialTransport, model: PowerSupplyModel) -> None:
        self._transport = transport
        self.model = model

    # -- validation --

    def _check_voltage(self, volts: float) -> float:
        if not (0.0 <= volts <= self.model.max_voltage):
            raise ValueError(
                f"Voltage {volts} V out of range for {self.model.name} "
                f"(0..{self.model.max_voltage} V)."
            )
        return volts

    def _check_current(self, amps: float) -> float:
        if not (0.0 <= amps <= self.model.max_current):
            raise ValueError(
                f"Current {amps} A out of range for {self.model.name} "
                f"(0..{self.model.max_current} A)."
            )
        return amps

    # -- identification --

    def identify(self) -> str:
        """Return the device identification string (``*IDN?``)."""
        return self._transport.query(protocol.cmd_identify()).decode(
            "ascii", errors="replace"
        ).strip()

    # -- setpoints --

    def set_voltage(self, volts: float) -> None:
        """Set the output voltage setpoint (validated against the model)."""
        self._check_voltage(volts)
        field = self.model.format_voltage(volts)
        self._transport.send(protocol.cmd_set_voltage(field))

    def get_voltage_setpoint(self) -> float:
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_voltage_setpoint())
        )

    def set_current(self, amps: float) -> None:
        """Set the output current limit (validated against the model)."""
        self._check_current(amps)
        field = self.model.format_current(amps)
        self._transport.send(protocol.cmd_set_current(field))

    def get_current_setpoint(self) -> float:
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_current_setpoint())
        )

    # -- live measurements --

    def measure_voltage(self) -> float:
        """Read the actual voltage at the output terminals (``VOUT1?``)."""
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_output_voltage())
        )

    def measure_current(self) -> float:
        """Read the actual current flowing from the output (``IOUT1?``)."""
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_output_current())
        )

    # -- output / protection control --

    def set_output(self, enabled: bool) -> None:
        """Enable or disable the output terminals (``OUT1`` / ``OUT0``)."""
        self._transport.send(protocol.cmd_set_output(enabled))

    def set_ocp(self, enabled: bool) -> None:
        """Arm or disarm over-current protection (``OCP1`` / ``OCP0``)."""
        self._transport.send(protocol.cmd_set_ocp(enabled))

    def get_status(self) -> Status:
        """Read and decode the status byte (``STATUS?``)."""
        return protocol.decode_status(
            self._transport.query(protocol.cmd_query_status())
        )

    # -- panel memory --

    def save(self, slot: int) -> None:
        """Store the current panel settings into memory *slot* (1..5)."""
        self._transport.send(protocol.cmd_save(slot))

    def recall(self, slot: int) -> None:
        """Recall panel settings from memory *slot* (1..5)."""
        self._transport.send(protocol.cmd_recall(slot))

    # -- composite --

    def snapshot(self) -> dict:
        """Return a single consolidated reading of the instrument state."""
        status = self.get_status()
        return {
            "model": self.model.name,
            "voltage_setpoint": self.get_voltage_setpoint(),
            "current_setpoint": self.get_current_setpoint(),
            "output_voltage": self.measure_voltage(),
            "output_current": self.measure_current(),
            "output_enabled": status.output_enabled,
            "mode": status.mode,
            "ocp_enabled": status.ocp_enabled,
        }

    def close(self) -> None:
        self._transport.close()
