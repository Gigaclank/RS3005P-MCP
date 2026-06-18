# Safety profiles (protecting the attached device)

The supply can deliver up to 30 V / 5 A, but the device wired to its terminals
(the DUT) usually tolerates far less. A **safety profile** describes a DUT's safe
operating envelope; once one is active, the server refuses any agent request
that would leave that envelope. This is the mechanism that stops an AI agent
from accidentally over-driving — and damaging — attached hardware.

## Trust model (what an agent can and can't do)

- The profile **library** is an operator-curated file (`RS3005P_PROFILE` env var
  or `--profile`). **No MCP tool can create or modify a profile's limits**, so an
  agent can never fabricate a wider envelope — the limits always come from a file
  only the operator writes.
- A tool *may* **select** which curated device is active (`select_device`,
  `connect(device=...)`, or the `RS3005P_DEVICE` default), so you don't have to
  re-register the server when you swap devices. Two guards make this safe:
  - **Confirm-to-widen:** switching to a profile whose envelope is wider in any
    dimension (higher voltage / current / power ceiling, or output newly
    allowed) is refused unless `confirm_widen=True`.
  - **Forced baseline on switch:** after any switch the supply is brought into
    the new envelope (output off / setpoints clamped) before anything else.
- **Residual risk you accept by enabling runtime selection:** if the *wrong*
  profile is selected for the hardware that is physically wired (e.g. the 3.3 V
  module is attached but the 23 V chassis profile is active), the supply will
  permit the wider profile's voltage. Software cannot detect what is on the
  terminals — matching the active profile to the attached device is the
  operator's responsibility. The confirm-to-widen gate bounds the blast radius.
- The library file is **re-read on every connect/select** (hot reload), so edits
  to `devices.json` take effect without re-registering the server.

## Guardrails enforced (in `device.py`, before any byte is sent)

| Guardrail            | Effect |
|----------------------|--------|
| Voltage ceiling      | `set_voltage` rejected above `voltage_max` (and the 30 V hardware max). |
| Current ceiling      | `set_current` rejected above `current_max` (and the 5 A hardware max). |
| Power ceiling        | Any setpoint whose V×I exceeds `power.max` is rejected. |
| Output gating        | `set_output(true)` refused if the profile forbids output, or if the present setpoints are outside the envelope. Disabling is always allowed. |
| Slew limiting        | A single `set_voltage` may not jump more than `max_voltage_step`; use `ramp_voltage`/`power_up` to reach a distant value gradually. |
| Connect baseline     | On connect, if the supply is outside the envelope it is forced to a safe baseline (output off; voltage to the floor; current to the cap). |
| Recall re-validation | `recall_settings` re-checks the restored preset; if unsafe, the supply is forced to a safe baseline and the call raises. |

### Voltage bounds: ceiling vs. band

`{"nominal": 24.0, "tolerance": 0.5}` means **ceiling = 24.5 V**, nominal target
= 24.0 V, and **floor = 0 V**. Over-voltage is the damage vector, so tolerance
sets only the upper safe limit; the agent may always set lower voltages (and
ramp up from 0 / wind down to off). If you genuinely need a hard *lower* floor,
use explicit bounds: `{"min": 20.0, "max": 24.5}`.

## Profile library format

One file holds many devices. Device names as keys:

```json
{
  "schema_version": "1.0",
  "devices": {
    "24v-sensor": {
      "device": "24 V industrial sensor",
      "voltage": { "nominal": 24.0, "tolerance": 0.5 },
      "current": { "max": 0.5, "nominal": 0.2 },
      "power":   { "max": 12.0 },
      "output_allowed": true,
      "max_voltage_step": 2.0
    },
    "5v-logic": {
      "voltage": { "min": 0.0, "max": 5.25 },
      "current": { "max": 1.0 }
    }
  }
}
```

…or a JSON array where each entry carries its own `name`. A bare single-profile
object (no `devices` wrapper) is also accepted. See
[`examples/devices.example.json`](../examples/devices.example.json).

Field reference (per device):

| Field              | Required | Meaning |
|--------------------|----------|---------|
| `device`           | no       | Human-readable description (defaults to the key/name). |
| `voltage`          | yes      | `{nominal, tolerance}` or `{min?, max}` (volts). |
| `current.max`      | yes      | Current ceiling (amps). |
| `current.nominal`  | no       | Operating current used by `power_up`. |
| `power.max`        | no       | V×I ceiling (watts). |
| `output_allowed`   | no       | Default `true`; set `false` to forbid enabling output. |
| `max_voltage_step` | no       | Largest allowed single voltage change (volts). |

## Usage

```bash
# select the 24 V sensor profile from a library at launch
rs3005p-mcp --profile devices.json --device 24v-sensor
# or via environment
RS3005P_PROFILE=devices.json RS3005P_DEVICE=24v-sensor uv run rs3005p-mcp
```

A single-device library needs no `--device` (the sole entry is selected); a
multi-device library requires it (fail-loud, so the operator must name what is
physically attached) — though it can also be chosen later at runtime.

### Switching device at runtime (no re-registration)

`RS3005P_DEVICE` only sets the *default*. Once running, an agent can switch among
the curated devices without restarting the server:

- `list_devices` — show the library and which device is active.
- `select_device(name)` — make `name` active; narrowing or equal envelopes apply
  immediately, widening requires `select_device(name, confirm_widen=true)`.
- `connect(port, device=name)` — select at connect time.

Editing `devices.json` (adding a device or changing limits) takes effect on the
next `connect`/`select_device` — no `claude mcp` re-registration needed.

With a profile active, `power_up` brings the DUT to its nominal operating point:
it sets the current limit to `current.nominal` (or `current.max`), ramps the
voltage to `voltage.nominal` within the slew limit, and enables the output.

## No profile = fail-loud

If no profile is configured the server still runs, limited only by the hardware
envelope (30 V / 5 A), and every `connect` / `get_safety_profile` response says
so explicitly. Supplying a profile is how an operator opts into DUT protection.
