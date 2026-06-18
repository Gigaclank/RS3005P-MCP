# RS Series Remote Control Syntax V2.0 — reference

Source: *RS3000/6000-Series User Manual*, "REMOTE CONTROL (RS-3005P &
RS-6005P)". This is the wire protocol implemented by
[`rs3005p_mcp/protocol.py`](../rs3005p_mcp/protocol.py).

## Serial line settings

| Parameter      | Value |
|----------------|-------|
| Baud rate      | 9600  |
| Data bits      | 8     |
| Parity         | None  |
| Stop bits      | 1     |
| Flow control   | None  |

The supply enumerates as a USB virtual COM port (or is wired via a straight
RS232 cable on pins 2/3/5). Documented response time is ~50 ms.

## Framing

- Commands are ASCII with **no terminator** — the bytes of the command are the
  whole message. (`rs3005p-mcp` therefore bounds reads with a serial timeout
  and flushes the input buffer before every exchange.)
- "Set" commands produce **no reply**.
- "Query" commands (those ending in `?`) reply with a fixed-format ASCII field,
  except `STATUS?` which replies with a single raw byte.

## Commands

`X` is the output channel and is always `1` on these single-output units.

| Command          | Direction | Reply            | Meaning                              |
|------------------|-----------|------------------|--------------------------------------|
| `*IDN?`          | query     | `KORAD RS3005P V2.0` | Identify (maker, model, fw version) |
| `VSET1:<nn.nn>`  | set       | —                | Set voltage setpoint (e.g. `VSET1:20.50`) |
| `VSET1?`         | query     | `nn.nn`          | Voltage setpoint                     |
| `ISET1:<n.nnn>`  | set       | —                | Set current limit (e.g. `ISET1:2.225`) |
| `ISET1?`         | query     | `n.nnn`          | Current setpoint                     |
| `VOUT1?`         | query     | `nn.nn`          | **Actual** output voltage            |
| `IOUT1?`         | query     | `n.nnn`          | **Actual** output current            |
| `OUT1` / `OUT0`  | set       | —                | Output on / off                      |
| `OCP1` / `OCP0`  | set       | —                | Over-current protection on / off     |
| `STATUS?`        | query     | 1 byte           | Status bits (below)                  |
| `SAV<n>`         | set       | —                | Store panel settings, memory `n` 1–5 |
| `RCL<n>`         | set       | —                | Recall panel settings, memory `n` 1–5 |

### Value formatting

The firmware expects fixed-width, zero-padded fields. These are defined per
model in [`models.py`](../rs3005p_mcp/models.py):

- Voltage: `{:05.2f}` → `05.00`, `12.34`, `30.00`, `60.00`.
- Current: `{:05.3f}` → `0.500`, `2.225`, `5.000`.

### `STATUS?` byte layout

| Bit | Item   | Meaning                          | Decoded by this server |
|-----|--------|----------------------------------|------------------------|
| 0   | CH1    | `0` = CC mode, `1` = CV mode     | ✅ `constant_voltage`  |
| 1   | CH2    | (n/a on single-output models)    | —                      |
| 2–3 | Track  | tracking mode                    | —                      |
| 4   | Beep   | beeper enabled                   | —                      |
| 5   | OCP    | over-current protection armed    | ✅ `ocp_enabled`       |
| 6   | Output | `0` = off, `1` = on              | ✅ `output_enabled`    |
| 7   | OVP    | over-voltage protection          | —                      |

Bits 1–4 and 7 appear only on multi-channel / extended variants; the raw byte
is always preserved in `Status.raw` for completeness.
