"""Operator-defined safety envelopes for the *attached* devices under test.

The instrument can deliver up to 30 V / 5 A, but whatever is wired to its
terminals usually tolerates far less. A :class:`SafetyProfile` describes one
attached device's safe operating envelope and is the mechanism by which an
operator stops an AI agent from driving the supply somewhere that would damage
the device under test (DUT).

A single file can hold a **library** of these profiles (one per bench device),
selected by name. Two equivalent layouts are accepted:

* device names as keys::

      {
        "schema_version": "1.0",
        "devices": {
          // tolerance sets the upper ceiling (24.5 V) + nominal target; floor is 0 V
          "24v-sensor": { "voltage": {"nominal": 24.0, "tolerance": 0.5},
                          "current": {"max": 0.5, "nominal": 0.2},
                          "power": {"max": 12.0}, "max_voltage_step": 2.0 },
          "5v-logic":   { "voltage": {"min": 0.0, "max": 5.25},
                          "current": {"max": 1.0} }
        }
      }

* or a JSON array (each entry carries its own ``name``)::

      { "schema_version": "1.0",
        "devices": [ {"name": "24v-sensor", "voltage": {...}, "current": {...}},
                     {"name": "5v-logic",   "voltage": {...}, "current": {...}} ] }

A bare single-profile object (no ``devices`` wrapper) is also accepted for the
one-device case.

Trust model: the library is loaded **at server startup** (file named by the
``RS3005P_PROFILE`` env var / ``--profile`` flag) and the active device is
chosen at startup too (``RS3005P_DEVICE`` env var / ``--device`` flag). Both are
immutable at runtime; **no MCP tool can create, modify or switch profiles** --
otherwise an agent could simply select a more permissive envelope. Profiles are
pure data + pure checks (no I/O), so the whole envelope is unit-testable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

SCHEMA_VERSION = "1.0"

# Float comparison tolerance so an exact boundary value (e.g. setting 24.5 when
# the max is 24.5) is accepted rather than rejected by rounding noise.
_EPS = 1e-6


@dataclass(frozen=True)
class SafetyProfile:
    """Immutable safe-operating envelope for one attached device under test.

    Attributes:
        name: Selector key for the device within a library (stable identifier).
        device: Human-readable description (defaults to ``name``).
        voltage_min/voltage_max: Allowed voltage setpoint bounds, volts.
        current_max: Highest allowed current setpoint, amps.
        power_max: Optional ceiling on V*I, watts (``None`` = unlimited).
        output_allowed: Whether the agent may enable the output at all.
        max_voltage_step: Optional cap on how far one ``set_voltage`` may jump.
        nominal_voltage/nominal_current: Optional intended operating point
            (used by the ``power_up`` convenience).
    """

    name: str
    device: str
    voltage_min: float
    voltage_max: float
    current_max: float
    power_max: float | None = None
    output_allowed: bool = True
    max_voltage_step: float | None = None
    nominal_voltage: float | None = None
    nominal_current: float | None = None

    # --- construction ---

    @classmethod
    def from_dict(cls, data: dict, name: str | None = None) -> "SafetyProfile":
        """Build (and validate) a single profile from a parsed JSON dict.

        *name* is the library key; if omitted it falls back to the dict's own
        ``name`` then ``device`` field.
        """
        resolved_name = name or data.get("name") or data.get("device")
        if not resolved_name:
            raise ValueError("Profile needs a 'name' (or a library key).")

        voltage = data.get("voltage")
        if not isinstance(voltage, dict):
            raise ValueError(f"Profile {resolved_name!r} must contain 'voltage'.")
        vmin, vmax, vnom = _resolve_voltage_bounds(voltage, resolved_name)

        current = data.get("current")
        if not isinstance(current, dict) or "max" not in current:
            raise ValueError(
                f"Profile {resolved_name!r} 'current' must specify 'max'."
            )
        imax = float(current["max"])
        inom = float(current["nominal"]) if "nominal" in current else None

        power = data.get("power") or {}
        pmax = float(power["max"]) if "max" in power else None

        profile = cls(
            name=str(resolved_name),
            device=str(data.get("device", resolved_name)),
            voltage_min=vmin,
            voltage_max=vmax,
            current_max=imax,
            power_max=pmax,
            output_allowed=bool(data.get("output_allowed", True)),
            max_voltage_step=(
                float(data["max_voltage_step"])
                if data.get("max_voltage_step") is not None
                else None
            ),
            nominal_voltage=vnom,
            nominal_current=inom,
        )
        profile._validate_self()
        return profile

    def _validate_self(self) -> None:
        if self.voltage_min < 0:
            raise ValueError(f"{self.name}: voltage min must be >= 0.")
        if self.voltage_max < self.voltage_min:
            raise ValueError(f"{self.name}: voltage max must be >= voltage min.")
        if self.current_max < 0:
            raise ValueError(f"{self.name}: current max must be >= 0.")
        if self.power_max is not None and self.power_max < 0:
            raise ValueError(f"{self.name}: power max must be >= 0.")
        if self.max_voltage_step is not None and self.max_voltage_step <= 0:
            raise ValueError(f"{self.name}: max_voltage_step must be > 0.")
        if self.nominal_voltage is not None and not (
            self.voltage_min - _EPS <= self.nominal_voltage <= self.voltage_max + _EPS
        ):
            raise ValueError(f"{self.name}: nominal voltage outside voltage bounds.")
        if self.nominal_current is not None and not (
            0 <= self.nominal_current <= self.current_max + _EPS
        ):
            raise ValueError(f"{self.name}: nominal current outside [0, max].")

    # --- pure checks (raise ValueError on violation) ---

    def check_voltage(self, volts: float) -> None:
        if not (self.voltage_min - _EPS <= volts <= self.voltage_max + _EPS):
            raise ValueError(
                f"Voltage {volts} V outside safe envelope for '{self.device}' "
                f"([{self.voltage_min}, {self.voltage_max}] V)."
            )

    def check_current(self, amps: float) -> None:
        if not (0 <= amps <= self.current_max + _EPS):
            raise ValueError(
                f"Current {amps} A outside safe envelope for '{self.device}' "
                f"([0, {self.current_max}] A)."
            )

    def check_power(self, volts: float, amps: float) -> None:
        if self.power_max is not None and volts * amps > self.power_max + _EPS:
            raise ValueError(
                f"Power {volts * amps:.3f} W (={volts} V x {amps} A) exceeds the "
                f"{self.power_max} W ceiling for '{self.device}'."
            )

    def check_step(self, present_volts: float, target_volts: float) -> None:
        if (
            self.max_voltage_step is not None
            and abs(target_volts - present_volts) > self.max_voltage_step + _EPS
        ):
            raise ValueError(
                f"Voltage jump {present_volts}->{target_volts} V exceeds the "
                f"{self.max_voltage_step} V per-step limit for '{self.device}'. "
                f"Ramp gradually (or use power_up)."
            )

    def check_output_allowed(self) -> None:
        if not self.output_allowed:
            raise ValueError(
                f"Output is disabled by the safety profile for '{self.device}'."
            )

    def as_dict(self) -> dict:
        return asdict(self)


def _resolve_voltage_bounds(
    voltage: dict, name: str
) -> tuple[float, float, float | None]:
    """Return ``(min, max, nominal)`` from either nominal+tolerance or min/max."""
    if "nominal" in voltage and "tolerance" in voltage:
        # tolerance defines the upper *safe ceiling* (over-voltage is the damage
        # vector) and the nominal operating point used by power_up. The floor
        # stays at 0 V so the agent can always ramp up from off / wind back down;
        # use explicit {min, max} if a hard lower floor is genuinely required.
        nominal = float(voltage["nominal"])
        tol = float(voltage["tolerance"])
        return 0.0, nominal + tol, nominal
    if "max" in voltage:
        vmin = float(voltage.get("min", 0.0))
        vmax = float(voltage["max"])
        nominal = float(voltage["nominal"]) if "nominal" in voltage else None
        return vmin, vmax, nominal
    raise ValueError(
        f"Profile {name!r} 'voltage' must specify either "
        f"{{nominal, tolerance}} or {{max}}."
    )


def _check_schema_version(data: dict) -> None:
    version = str(data.get("schema_version", SCHEMA_VERSION))
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported profile schema_version {version!r}; "
            f"this server understands {SCHEMA_VERSION!r}."
        )


def load_profiles(path: str) -> dict[str, SafetyProfile]:
    """Load a profile library from *path* into a ``{name: SafetyProfile}`` map.

    Accepts a device-keyed object, a JSON array of profiles, or a bare single
    profile (see the module docstring for layouts).
    """
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):  # bare array
        entries: object = data
    elif isinstance(data, dict):
        _check_schema_version(data)
        if "devices" in data:
            entries = data["devices"]
        elif "voltage" in data:  # bare single profile
            entries = [data]
        else:  # treat remaining keys as name -> profile mapping
            entries = {
                k: v for k, v in data.items() if k != "schema_version"
            }
    else:
        raise ValueError("Profile file must be a JSON object or array.")

    profiles: dict[str, SafetyProfile] = {}
    if isinstance(entries, dict):
        for key, entry in entries.items():
            profiles[key] = SafetyProfile.from_dict(entry, name=key)
    elif isinstance(entries, list):
        for entry in entries:
            profile = SafetyProfile.from_dict(entry)
            profiles[profile.name] = profile
    else:
        raise ValueError("'devices' must be an object or an array.")

    if not profiles:
        raise ValueError(f"No device profiles found in {path!r}.")
    return profiles


def select_profile(
    profiles: dict[str, SafetyProfile], requested: str | None
) -> SafetyProfile:
    """Choose the active profile from a library.

    If *requested* is given it must match a key. If omitted, a single-profile
    library is used directly; a multi-profile library raises (fail-loud) so the
    operator must name which device is physically attached.
    """
    if requested is not None:
        if requested not in profiles:
            raise ValueError(
                f"Device {requested!r} not in profile library; "
                f"available: {sorted(profiles)}."
            )
        return profiles[requested]
    if len(profiles) == 1:
        return next(iter(profiles.values()))
    raise ValueError(
        f"Multiple device profiles available {sorted(profiles)}; set "
        f"RS3005P_DEVICE (or --device) to name the attached device."
    )
