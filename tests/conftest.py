"""Test fixtures: an in-memory emulator of the RS-3005P serial behaviour.

`FakeKorad` implements the `SerialLike` protocol and mimics the firmware's
request/response semantics closely enough to exercise the transport, protocol
and device layers end-to-end without hardware: no terminators, set-commands are
silent, queries return fixed-format ASCII (or a single status byte).
"""

from __future__ import annotations

import pytest

from rs3005p_mcp.device import PowerSupply
from rs3005p_mcp.models import MODELS
from rs3005p_mcp.transport import SerialTransport


class FakeKorad:
    """Minimal emulator of a KORAD RS3005P over the serial wire."""

    def __init__(self, idn: str = "KORAD RS3005P V2.0") -> None:
        self.idn = idn
        self.vset = 0.0
        self.iset = 0.0
        self.output = False
        self.ocp = False
        self.constant_voltage = True
        self._memory: dict[int, tuple[float, float]] = {}
        self._out = bytearray()  # bytes pending to be read back
        self._open = True
        self.written: list[bytes] = []  # log of commands received

    # --- SerialLike interface ---

    @property
    def is_open(self) -> bool:
        return self._open

    def reset_input_buffer(self) -> None:
        self._out.clear()

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        self._handle(bytes(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        chunk = bytes(self._out[:size])
        del self._out[:size]
        return chunk

    def close(self) -> None:
        self._open = False

    # --- emulated firmware ---

    def _reply(self, data: bytes) -> None:
        self._out.extend(data)

    def _status_byte(self) -> int:
        raw = 0
        if self.constant_voltage:
            raw |= 1 << 0
        if self.ocp:
            raw |= 1 << 5
        if self.output:
            raw |= 1 << 6
        return raw

    def _handle(self, cmd: bytes) -> None:
        text = cmd.decode("ascii")
        if text == "*IDN?":
            self._reply(self.idn.encode("ascii"))
        elif text == "VSET1?":
            self._reply(f"{self.vset:05.2f}".encode("ascii"))
        elif text == "ISET1?":
            self._reply(f"{self.iset:05.3f}".encode("ascii"))
        elif text == "VOUT1?":
            value = self.vset if self.output else 0.0
            self._reply(f"{value:05.2f}".encode("ascii"))
        elif text == "IOUT1?":
            value = self.iset if self.output else 0.0
            self._reply(f"{value:05.3f}".encode("ascii"))
        elif text == "STATUS?":
            self._reply(bytes([self._status_byte()]))
        elif text.startswith("VSET1:"):
            self.vset = float(text.split(":", 1)[1])
        elif text.startswith("ISET1:"):
            self.iset = float(text.split(":", 1)[1])
        elif text == "OUT1":
            self.output = True
        elif text == "OUT0":
            self.output = False
        elif text == "OCP1":
            self.ocp = True
        elif text == "OCP0":
            self.ocp = False
        elif text.startswith("SAV"):
            self._memory[int(text[3:])] = (self.vset, self.iset)
        elif text.startswith("RCL"):
            slot = int(text[3:])
            if slot in self._memory:
                self.vset, self.iset = self._memory[slot]
        # Unknown commands are ignored, like the real firmware.


@pytest.fixture
def fake() -> FakeKorad:
    return FakeKorad()


@pytest.fixture
def transport(fake: FakeKorad) -> SerialTransport:
    # command_delay=0 keeps the suite fast; the fake needs no settle time.
    return SerialTransport(fake, command_delay=0.0)


@pytest.fixture
def device(transport: SerialTransport) -> PowerSupply:
    return PowerSupply(transport, MODELS["RS-3005P"])
