"""Pure encode/decode for the RS Series Remote Control Syntax V2.0.

This module has no I/O and no knowledge of serial ports: it only turns
intentions into command byte-strings and turns raw response bytes into Python
values. That makes the entire wire protocol exhaustively unit-testable without
hardware.

Protocol facts (from the RS3000/6000-Series User Manual, "REMOTE CONTROL"):
  * Serial line settings: 9600 baud, 8 data bits, no parity, 1 stop bit, no
    flow control.
  * Commands are ASCII with **no terminator** (no CR/LF appended).
  * "Set" commands produce no reply; "query" commands (ending in ``?``) reply
    with ASCII (floats) or, for ``STATUS?``, a single raw status byte.
  * Documented response time is ~50 ms.

Command summary (channel ``X`` is always ``1`` on these single-output units):
  ``*IDN?``            -> identification string (e.g. ``KORAD RS3005P V2.0``)
  ``VSET1:<nn.nn>``    -> set output voltage setpoint
  ``VSET1?``           -> query voltage setpoint
  ``ISET1:<n.nnn>``    -> set output current setpoint
  ``ISET1?``           -> query current setpoint
  ``VOUT1?``           -> read *actual* output voltage
  ``IOUT1?``           -> read *actual* output current
  ``OUT1`` / ``OUT0``  -> output on / off
  ``OCP1`` / ``OCP0``  -> over-current protection on / off
  ``STATUS?``          -> 8-bit status byte
  ``SAV<n>``           -> store panel settings to memory n (1..5)
  ``RCL<n>``           -> recall panel settings from memory n (1..5)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

PROTOCOL_VERSION = "2.0"

DEFAULT_CHANNEL = 1
MEMORY_SLOT_MIN = 1
MEMORY_SLOT_MAX = 5

# Status byte bit positions (manual "STATUS?" table, merged with the extended
# Chinese-language table which documents bits beyond the EN single-channel set).
_STATUS_BIT_CV = 0  # 0 = constant current, 1 = constant voltage
_STATUS_BIT_OCP = 5  # over-current protection enabled
_STATUS_BIT_OUTPUT = 6  # output on/off

# A float field: optional sign, digits, optional decimal part. Used to extract a
# value from a response that may carry stray whitespace or trailing bytes.
_FLOAT_RE = re.compile(rb"[-+]?\d*\.?\d+")


@dataclass(frozen=True)
class Status:
    """Decoded view of the single ``STATUS?`` byte.

    Attributes:
        raw: The undecoded status byte (0-255), preserved for debugging.
        output_enabled: True if the output terminals are live.
        constant_voltage: True in CV mode, False in CC (current-limited) mode.
        ocp_enabled: True if over-current protection is armed.
    """

    raw: int
    output_enabled: bool
    constant_voltage: bool
    ocp_enabled: bool

    @property
    def constant_current(self) -> bool:
        """Convenience inverse of :attr:`constant_voltage`."""
        return not self.constant_voltage

    @property
    def mode(self) -> str:
        """Human-readable regulation mode, ``"CV"`` or ``"CC"``."""
        return "CV" if self.constant_voltage else "CC"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["mode"] = self.mode
        return data


def _validate_channel(channel: int) -> int:
    if channel != DEFAULT_CHANNEL:
        raise ValueError(
            f"RS-3005P/RS-6005P have a single output; channel must be "
            f"{DEFAULT_CHANNEL}, got {channel}."
        )
    return channel


def _validate_slot(slot: int) -> int:
    if not isinstance(slot, int) or not (MEMORY_SLOT_MIN <= slot <= MEMORY_SLOT_MAX):
        raise ValueError(
            f"Memory slot must be an integer in "
            f"[{MEMORY_SLOT_MIN}, {MEMORY_SLOT_MAX}], got {slot!r}."
        )
    return slot


# --- command encoders -------------------------------------------------------


def cmd_identify() -> bytes:
    return b"*IDN?"


def cmd_set_voltage(field: str, channel: int = DEFAULT_CHANNEL) -> bytes:
    """Encode a voltage-setpoint command. *field* is the already-formatted
    ASCII value (see :meth:`PowerSupplyModel.format_voltage`)."""
    _validate_channel(channel)
    return f"VSET{channel}:{field}".encode("ascii")


def cmd_query_voltage_setpoint(channel: int = DEFAULT_CHANNEL) -> bytes:
    _validate_channel(channel)
    return f"VSET{channel}?".encode("ascii")


def cmd_set_current(field: str, channel: int = DEFAULT_CHANNEL) -> bytes:
    """Encode a current-setpoint command. *field* is the already-formatted
    ASCII value (see :meth:`PowerSupplyModel.format_current`)."""
    _validate_channel(channel)
    return f"ISET{channel}:{field}".encode("ascii")


def cmd_query_current_setpoint(channel: int = DEFAULT_CHANNEL) -> bytes:
    _validate_channel(channel)
    return f"ISET{channel}?".encode("ascii")


def cmd_query_output_voltage(channel: int = DEFAULT_CHANNEL) -> bytes:
    _validate_channel(channel)
    return f"VOUT{channel}?".encode("ascii")


def cmd_query_output_current(channel: int = DEFAULT_CHANNEL) -> bytes:
    _validate_channel(channel)
    return f"IOUT{channel}?".encode("ascii")


def cmd_set_output(enabled: bool) -> bytes:
    return b"OUT1" if enabled else b"OUT0"


def cmd_set_ocp(enabled: bool) -> bytes:
    return b"OCP1" if enabled else b"OCP0"


def cmd_query_status() -> bytes:
    return b"STATUS?"


def cmd_save(slot: int) -> bytes:
    return f"SAV{_validate_slot(slot)}".encode("ascii")


def cmd_recall(slot: int) -> bytes:
    return f"RCL{_validate_slot(slot)}".encode("ascii")


# --- response decoders ------------------------------------------------------


def parse_float(response: bytes) -> float:
    """Extract a float from a (possibly noisy) ASCII response.

    The firmware sends fixed-width fields with no terminator; in practice
    responses can carry stray whitespace or a trailing byte, so we extract the
    first numeric token rather than trusting the exact framing.
    """
    match = _FLOAT_RE.search(response)
    if not match:
        raise ValueError(f"No numeric value in response {response!r}.")
    return float(match.group())


def decode_status(response: bytes) -> Status:
    """Decode the single status byte returned by ``STATUS?``."""
    if not response:
        raise ValueError("Empty STATUS? response.")
    raw = response[0]
    return Status(
        raw=raw,
        output_enabled=bool(raw & (1 << _STATUS_BIT_OUTPUT)),
        constant_voltage=bool(raw & (1 << _STATUS_BIT_CV)),
        ocp_enabled=bool(raw & (1 << _STATUS_BIT_OCP)),
    )
