# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP server that lets AI agents drive an **RS PRO RS-3005P / RS-6005P** programmable DC power supply over its USB/RS232 serial port, implementing the manual's *RS Series Remote Control Syntax V2.0* (KORAD-compatible).

## Commands

```bash
uv venv                       # create the virtualenv (Python; uv-managed)
uv pip install -e ".[dev]"    # install with test deps
uv run pytest                 # full suite + coverage (configured in pyproject.toml)
uv run pytest tests/test_protocol.py::test_parse_float   # single test
uv run rs3005p-mcp            # run the MCP server over stdio
```

There is no separate lint step configured. Coverage is reported automatically (`--cov` is in `pyproject.toml addopts`); the suite runs with **no hardware** against an in-memory emulator.

## Architecture

Six layers, each isolating one concern so the protocol and safety logic can be proven without hardware. Data flows: MCP client → `server` → `device` → (`protocol` + `transport`) → serial port, with `device` also consulting a `safety` profile.

- **`models.py`** — frozen `PowerSupplyModel` table (RS-3005P = 0–30 V, RS-6005P = 0–60 V). Holds output limits **and** the exact ASCII number format the firmware expects (`format_voltage`/`format_current`). Add a variant = one dict entry; never hard-code limits or formats elsewhere.
- **`protocol.py`** — **pure** functions only (no I/O): `cmd_*` encode intentions to command bytes, `parse_float`/`decode_status` decode raw replies. This is the single source of truth for the wire protocol. `parse_float` extracts the first numeric token (tolerant of stray trailing bytes seen on real units).
- **`transport.py`** — serial framing/timing. The `serial.Serial` object is **injected** into `SerialTransport`, not constructed inside it — that injection is what lets tests substitute the fake. `open_serial()` is the only place pyserial is imported (lazily). Handles the firmware quirks: no command terminators, ~50 ms inter-command delay, input-buffer flush before each exchange, a lock around request/response.
- **`safety.py`** — **pure** data + checks (no I/O): `SafetyProfile` is an operator-defined safe envelope for the *attached device under test*. `load_profiles`/`select_profile` parse a multi-device library file. This is the agent-proof guardrail; see "Safety model" below.
- **`device.py`** — `PowerSupply`, the API the server uses. Enforces two tiers **before** transmission: the model's hardware envelope, then (if attached) the `SafetyProfile`. Out-of-envelope requests raise instead of reaching hardware. `_force_safe_baseline`/`enforce_safe_on_connect` recover a supply found in an unsafe state.
- **`server.py`** — thin `@mcp.tool()` wrappers returning JSON-friendly dicts; owns one module-global `_device` connection (`connect`/`disconnect` lifecycle). Resolves the active profile from the environment at connect (`_active_profile`). Keep logic out of here — it belongs in `device`/`protocol`/`safety`.

## Safety model

Load-bearing invariant — **do not weaken it**: the safety profile is loaded at server **startup** from `RS3005P_PROFILE` (file) + `RS3005P_DEVICE` (selector), or `--profile`/`--device`. It is immutable at runtime and **no MCP tool may create, modify, or switch it** — otherwise an agent could widen its own limits. Tools may only *read* it (`get_safety_profile`). Enforcement (V/I/power ceilings, output gating, slew limiting, connect/recall safe-baseline reset) lives in `device.py`; pure checks live in `safety.py`. Voltage `nominal±tolerance` sets the **upper ceiling** + nominal target with the floor at 0 V (ramping up / switching off must always be allowed); a hard floor needs explicit `{min, max}`. See `docs/safety.md`.

## Firmware/protocol facts that bite

- Commands are ASCII with **no terminator**; "set" commands get no reply, queries reply with fixed-width ASCII (5 chars for floats) or, for `STATUS?`, a single raw byte. Serial is fixed at 9600-8-N-1.
- Real-hardware `*IDN?` returns e.g. `RS-3005P V6.9 SN:...`, **not** the manual's `KORAD RS3005P V2.0`. `connect` intentionally does not hard-match the IDN string.
- `STATUS?` byte: bit0 = CV(1)/CC(0), bit5 = OCP, bit6 = output on/off. The CV/CC bit is only meaningful while the output is **on** — when output is off the device reports `mode="CC"`, which is not significant.
- These are single-output units: the channel is always `1`; `protocol` rejects any other channel.

## Conventions

- The protocol/transport split is load-bearing for testability — keep `protocol.py` I/O-free and keep the serial object injectable. New device capabilities should add a `cmd_*` (+ decoder) in `protocol`, a validated method in `device`, an emulator branch in `tests/conftest.py::FakeKorad`, then a thin tool in `server`.
- See `docs/protocol.md` (command reference + status-byte table), `docs/architecture.md` (layer diagram + manual hardware-verification steps), and `docs/safety.md` (profile schema + guardrails).
