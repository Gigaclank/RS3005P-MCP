"""Serial transport: framing, timing and thread-safety for the V2.0 protocol.

The firmware quirks this layer absorbs:

* Commands have no terminator, so a "set" is just the bytes; reads after a
  query must be bounded by a timeout rather than waiting for a newline.
* The documented ~50 ms response time means back-to-back commands need a small
  inter-command gap, otherwise the device drops or merges them.
* The input buffer is flushed before each exchange so a query never reads a
  stale reply left over from a previous, mistimed command.

The actual ``serial.Serial`` object is injected (not constructed here) so the
whole transport can be exercised against an in-memory fake in tests.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class SerialLike(Protocol):
    """The subset of ``serial.Serial`` this transport relies on."""

    def write(self, data: bytes) -> int | None: ...
    def read(self, size: int = 1) -> bytes: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...
    @property
    def is_open(self) -> bool: ...


class SerialTransport:
    """Synchronous, locked request/response transport over a serial line."""

    def __init__(
        self,
        connection: SerialLike,
        command_delay: float = 0.05,
        read_chunk: int = 64,
    ) -> None:
        """
        Args:
            connection: An open serial-like object. Its read timeout governs how
                long :meth:`query` waits for reply bytes, so configure it on the
                ``serial.Serial`` instance (see :func:`open_serial`).
            command_delay: Seconds to pause after writing, to respect the
                device's ~50 ms response time.
            read_chunk: Bytes requested per read while draining a reply.
        """
        self._conn = connection
        self._command_delay = command_delay
        self._read_chunk = read_chunk
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._conn.is_open

    def send(self, command: bytes) -> None:
        """Write a command that expects no reply (a "set")."""
        with self._lock:
            self._write(command)

    def query(self, command: bytes) -> bytes:
        """Write a command and return its reply bytes (drained until idle)."""
        with self._lock:
            self._write(command)
            return self._read_until_idle()

    def close(self) -> None:
        with self._lock:
            if self._conn.is_open:
                self._conn.close()

    # -- internals (call only while holding the lock) --

    def _write(self, command: bytes) -> None:
        self._conn.reset_input_buffer()
        self._conn.write(command)
        if self._command_delay:
            time.sleep(self._command_delay)

    def _read_until_idle(self) -> bytes:
        """Read until a read returns nothing (i.e. the timeout elapses).

        Relies on the underlying serial read timeout to terminate; a real
        ``serial.Serial`` blocks up to that timeout, an empty fake returns
        immediately.
        """
        chunks: list[bytes] = []
        while True:
            chunk = self._conn.read(self._read_chunk)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


def open_serial(
    port: str,
    baudrate: int = 9600,
    read_timeout: float = 0.2,
    command_delay: float = 0.05,
) -> SerialTransport:
    """Open *port* with the manual's 8-N-1 settings and wrap it in a transport.

    ``pyserial`` is imported lazily so the protocol/transport logic can be
    imported (and tested) without the dependency installed.
    """
    import serial  # local import: optional at module-import time

    connection = serial.Serial(
        port=port,
        baudrate=baudrate,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=read_timeout,
        write_timeout=read_timeout,
    )
    return SerialTransport(connection, command_delay=command_delay)
