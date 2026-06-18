# Architecture

The package is deliberately layered so that protocol correctness can be proven
without hardware, and so the serial/MCP concerns stay out of the protocol logic.

```
        MCP client (AI agent)
                │  stdio (JSON-RPC)
        ┌───────▼────────┐
        │   server.py    │  FastMCP tools; owns one active connection
        └───────┬────────┘
        ┌───────▼────────┐
        │   device.py    │  PowerSupply: high-level ops + range validation
        └───────┬────────┘
     ┌──────────┴───────────┐
┌────▼─────┐          ┌──────▼──────┐
│protocol.py│          │transport.py │
│ encode/   │          │ framing,    │
│ decode    │          │ timing,lock │
│ (pure)    │          └──────┬──────┘
└──────────┘                  │ SerialLike
                       ┌───────▼────────┐
                       │ serial.Serial  │  (or FakeKorad in tests)
                       └────────────────┘
```

## Layer responsibilities

- **`models.py`** — versioned table of hardware variants: output limits and the
  exact ASCII number format each expects. Adding a variant is one entry.
- **`protocol.py`** — *pure* functions: intentions → command bytes, and raw
  bytes → Python values (`Status`, floats). No I/O, so it is exhaustively
  unit-testable. This is the single source of truth for the wire protocol.
- **`transport.py`** — absorbs the firmware's quirks: no terminators (reads are
  timeout-bounded), the ~50 ms response gap, input-buffer flushing, and a lock
  so concurrent tool calls can't interleave on the wire. The `serial.Serial`
  object is *injected*, not constructed here, which is what lets the fake device
  stand in during tests.
- **`device.py`** — the `PowerSupply` API the server uses. Adds the safety the
  protocol layer omits: setpoints are validated against the model's envelope
  **before** transmission, so out-of-range requests raise rather than reaching
  hardware.
- **`server.py`** — thin MCP wrappers returning JSON-friendly dicts. No logic
  lives here beyond connection lifecycle.

## Testing strategy

`tests/conftest.py` provides `FakeKorad`, an in-memory emulator implementing the
`SerialLike` protocol with the real firmware's request/response semantics. It
lets the transport, protocol and device layers be exercised end-to-end with no
instrument attached. Run with `uv run pytest` (coverage is reported by default
via `pyproject.toml`).

The only paths not covered by unit tests are those that touch a physical port
(`transport.open_serial`'s `serial.Serial` construction) and the stdio entry
point (`__main__.main` / `mcp.run`); these require real hardware or a live MCP
client and are verified manually.

## Manual hardware verification

With a supply connected:

1. `uv run rs3005p-mcp` (or wire it into your MCP client).
2. `list_serial_ports` → confirm the port.
3. `connect(port=...)` → expect `identification` like `KORAD RS3005P V2.0`.
4. `set_voltage(5.0)`, `set_current(0.5)`, `set_output(true)`.
5. `measure()` → expect ~5 V and the load-dependent current.
