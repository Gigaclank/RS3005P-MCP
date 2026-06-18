# rs3005p-mcp

An [MCP](https://modelcontextprotocol.io) server that lets AI agents control an
**RS PRO RS-3005P** (or **RS-6005P**) digital programmable DC power supply over
its USB / RS232 serial interface.

It implements the documented *RS Series Remote Control Syntax V2.0*
(KORAD-compatible) and exposes voltage/current control, live measurements,
output and over-current-protection switching, and panel-memory save/recall as
MCP tools.

## Supported hardware

| Model      | Voltage | Current | Remote interface |
|------------|---------|---------|------------------|
| RS-3005P   | 0–30 V  | 0–5 A   | USB + RS232      |
| RS-6005P   | 0–60 V  | 0–5 A   | USB + RS232      |

The non-`P` variants (RS-3005D / RS-6005D) have **no** remote interface and
cannot be driven by this server.

Serial settings (fixed by the firmware): **9600 baud, 8 data bits, no parity,
1 stop bit, no flow control**.

## Install

```bash
uv venv
uv pip install -e .
```

## Run

The server speaks MCP over stdio:

```bash
uv run rs3005p-mcp
```

### Claude Code / Claude Desktop config

```json
{
  "mcpServers": {
    "rs3005p": {
      "command": "uv",
      "args": ["run", "rs3005p-mcp"],
      "cwd": "C:/path/to/rs3005p-mcp"
    }
  }
}
```

## Tools

| Tool                 | Purpose                                            |
|----------------------|----------------------------------------------------|
| `list_serial_ports`  | Discover the COM/tty port the supply is on.        |
| `connect`            | Open the port, pick the model, verify with `*IDN?`.|
| `disconnect`         | Close the connection.                              |
| `get_identification` | Read the `*IDN?` string.                           |
| `get_safety_profile` | Read the active safety envelope (read-only).       |
| `list_devices`       | List device profiles in the library + which is active.|
| `select_device`      | Switch active profile (widening needs `confirm_widen`).|
| `set_voltage`        | Set the voltage setpoint (range + safety validated).|
| `set_current`        | Set the current limit (range + safety validated).  |
| `ramp_voltage`       | Ramp voltage to a target within the slew limit.    |
| `power_up`           | Bring the DUT to its profile's nominal operating point.|
| `get_setpoints`      | Read configured voltage & current setpoints.       |
| `measure`            | Read *actual* output voltage & current.            |
| `set_output`         | Enable/disable the output terminals.               |
| `set_ocp`            | Arm/disarm over-current protection.                |
| `get_status`         | Decoded status: output, CV/CC mode, OCP.           |
| `get_state`          | Full snapshot (setpoints + measurements + status). |
| `save_settings`      | Store panel settings to memory slot 1–5.           |
| `recall_settings`    | Recall panel settings from memory slot 1–5.        |

## Safety profiles (protecting attached devices)

To stop an agent from over-driving the device wired to the terminals, supply a
**device-profile library** at launch. It defines a safe envelope (voltage /
current / power ceilings, output gating, slew limit) per device; the server
rejects any agent request that would leave it. Profiles are set by the operator
at startup and **cannot be changed by any tool**.

```bash
rs3005p-mcp --profile devices.json --device 24v-sensor
```

`RS3005P_DEVICE`/`--device` is only the *default*; an agent can switch among the
curated devices at runtime with `select_device` (widening the envelope requires
`confirm_widen=true`) and `devices.json` edits hot-reload on the next
`connect`/`select_device` — no re-registration. No tool can create or modify a
profile's limits; the file stays operator-curated.

See [`docs/safety.md`](docs/safety.md) and
[`examples/devices.example.json`](examples/devices.example.json). With no profile
the server runs limited only by hardware (30 V / 5 A) and says so on every
`connect`.

A typical agent flow:

1. `list_serial_ports` → find the port.
2. `connect(port="COM4")` → verifies identity, applies RS-3005P limits.
3. `set_voltage(5.0)`, `set_current(0.5)`.
4. `set_output(True)`.
5. `measure()` → live readings.

## Development

```bash
uv pip install -e ".[dev]"
uv run pytest
```

Tests run against an in-memory device emulator (`tests/conftest.py`), so no
hardware is required. See [`docs/`](docs/) for the protocol reference and
architecture notes.

## License

MIT.
