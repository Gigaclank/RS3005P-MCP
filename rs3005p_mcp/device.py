"""High-level instrument operations with range + safety-envelope validation.

This is the layer an application (or the MCP server) talks to. It combines the
pure :mod:`protocol` encoders/decoders with a :class:`SerialTransport`, and adds
two tiers of protection the protocol layer deliberately omits:

1. **Hardware envelope** -- setpoints are validated against the connected
   model's absolute limits (e.g. 0-30 V on RS-3005P).
2. **Safety envelope** -- if an operator-supplied :class:`SafetyProfile` is
   attached, setpoints are *additionally* validated against the safe operating
   limits of the device under test (V/I ceilings, power ceiling, slew rate,
   output gating). Both tiers run *before* any byte is transmitted, so an unsafe
   request raises instead of reaching hardware.

Extra serial round-trips (reading the present setpoint for slew/power checks)
are incurred only when the relevant profile limit is actually configured, so an
un-profiled session keeps the fast path.
"""

from __future__ import annotations

import time

from . import protocol
from .models import PowerSupplyModel
from .protocol import Status
from .safety import SafetyProfile
from .transport import SerialTransport


class PowerSupply:
    """A connected RS-3005P / RS-6005P, driven over a serial transport."""

    def __init__(
        self,
        transport: SerialTransport,
        model: PowerSupplyModel,
        profile: SafetyProfile | None = None,
    ) -> None:
        self._transport = transport
        self.model = model
        self.profile = profile

    # -- hardware-envelope validation --

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
        return (
            self._transport.query(protocol.cmd_identify())
            .decode("ascii", errors="replace")
            .strip()
        )

    # -- setpoints --

    def set_voltage(self, volts: float) -> None:
        """Set the output voltage setpoint, enforcing hardware + safety limits."""
        self._check_voltage(volts)
        if self.profile is not None:
            self.profile.check_voltage(volts)
            if self.profile.max_voltage_step is not None:
                self.profile.check_step(self.get_voltage_setpoint(), volts)
            if self.profile.power_max is not None:
                self.profile.check_power(volts, self.get_current_setpoint())
        field = self.model.format_voltage(volts)
        self._transport.send(protocol.cmd_set_voltage(field))

    def get_voltage_setpoint(self) -> float:
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_voltage_setpoint())
        )

    def set_current(self, amps: float) -> None:
        """Set the output current limit, enforcing hardware + safety limits."""
        self._check_current(amps)
        if self.profile is not None:
            self.profile.check_current(amps)
            if self.profile.power_max is not None:
                self.profile.check_power(self.get_voltage_setpoint(), amps)
        field = self.model.format_current(amps)
        self._transport.send(protocol.cmd_set_current(field))

    def get_current_setpoint(self) -> float:
        return protocol.parse_float(
            self._transport.query(protocol.cmd_query_current_setpoint())
        )

    def ramp_voltage(self, target: float, step_dwell: float = 0.05) -> None:
        """Ramp the voltage setpoint to *target*, respecting the slew limit.

        With no slew limit configured this is a single ``set_voltage``; with a
        limit it walks toward the target in steps no larger than the profile's
        ``max_voltage_step`` (each step is itself fully validated).
        """
        self._check_voltage(target)
        if self.profile is not None:
            self.profile.check_voltage(target)

        step = self.profile.max_voltage_step if self.profile else None
        if step is None:
            self.set_voltage(target)
            return

        current = self.get_voltage_setpoint()
        while abs(target - current) > 1e-6:
            direction = step if target > current else -step
            nxt = current + direction
            if (direction > 0 and nxt > target) or (direction < 0 and nxt < target):
                nxt = target
            nxt = round(nxt, 3)
            self.set_voltage(nxt)
            current = nxt
            if step_dwell:
                time.sleep(step_dwell)

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
        """Enable or disable the output terminals (``OUT1`` / ``OUT0``).

        Disabling is always permitted (it is the safe direction). Enabling is
        gated by the safety profile: the profile must allow output, and the
        *present* setpoints must already sit within the safe envelope.
        """
        if enabled and self.profile is not None:
            self.profile.check_output_allowed()
            volts = self.get_voltage_setpoint()
            amps = self.get_current_setpoint()
            self.profile.check_voltage(volts)
            self.profile.check_current(amps)
            if self.profile.power_max is not None:
                self.profile.check_power(volts, amps)
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
        """Recall panel settings from memory *slot* (1..5).

        A recalled preset may carry setpoints outside the safe envelope, so when
        a profile is active the restored state is re-validated; if unsafe, the
        output is forced off and the recall raises.
        """
        self._transport.send(protocol.cmd_recall(slot))
        if self.profile is not None:
            issues = self._envelope_issues()
            if issues:
                actions = self._force_safe_baseline()
                raise ValueError(
                    f"Recalled preset {slot} is outside the safe envelope "
                    f"({'; '.join(issues)}). Corrective action: {'; '.join(actions)}."
                )

    # -- safety auditing --

    def _envelope_issues(self) -> list[str]:
        """Return reasons the present setpoints violate the profile (if any)."""
        if self.profile is None:
            return []
        issues: list[str] = []
        volts = self.get_voltage_setpoint()
        amps = self.get_current_setpoint()
        for check in (
            lambda: self.profile.check_voltage(volts),
            lambda: self.profile.check_current(amps),
            lambda: self.profile.check_power(volts, amps),
        ):
            try:
                check()
            except ValueError as exc:
                issues.append(str(exc))
        return issues

    def _force_safe_baseline(self) -> list[str]:
        """Force the instrument into a safe state, bypassing the slew limit.

        Turns the output off and resets any out-of-envelope setpoint directly to
        a safe value (voltage to the floor; current to the cap). The slew limit
        is intentionally bypassed: moving *toward* safety is always permitted,
        and a slew-limited step-down could otherwise be blocked by the very
        over-limit value we are trying to escape. Returns a list of actions.
        """
        assert self.profile is not None
        actions: list[str] = []
        if self.get_status().output_enabled:
            self._transport.send(protocol.cmd_set_output(False))
            actions.append("output forced OFF (was live outside the safe envelope)")

        volts = self.get_voltage_setpoint()
        amps = self.get_current_setpoint()
        eps = 1e-6
        voltage_unsafe = (
            volts > self.profile.voltage_max + eps
            or volts < self.profile.voltage_min - eps
        )
        power_unsafe = (
            self.profile.power_max is not None
            and volts * amps > self.profile.power_max + eps
        )
        if voltage_unsafe or power_unsafe:
            floor = self.profile.voltage_min
            self._transport.send(
                protocol.cmd_set_voltage(self.model.format_voltage(floor))
            )
            actions.append(f"voltage setpoint reset {volts}->{floor} V")
        if amps > self.profile.current_max + eps:
            cap = self.profile.current_max
            self._transport.send(
                protocol.cmd_set_current(self.model.format_current(cap))
            )
            actions.append(f"current limit reset {amps}->{cap} A")
        return actions

    def enforce_safe_on_connect(self) -> list[str]:
        """Bring the supply to a safe baseline if it is outside the envelope.

        Called once at connect so a supply left in an unsafe state by a previous
        session (or a freshly attached DUT) can't be immediately harmed. Returns
        human-readable warnings describing any corrective action taken.
        """
        if self.profile is None or not self._envelope_issues():
            return []
        return self._force_safe_baseline()

    # -- composite --

    def snapshot(self) -> dict:
        """Return a single consolidated reading of the instrument state."""
        status = self.get_status()
        return {
            "model": self.model.name,
            "profile": self.profile.name if self.profile else None,
            "device": self.profile.device if self.profile else None,
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
