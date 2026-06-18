"""Unit tests for the serial transport layer against the fake device."""

from __future__ import annotations

from rs3005p_mcp.transport import SerialLike, SerialTransport
from tests.conftest import FakeKorad


def test_fake_satisfies_serial_protocol(fake: FakeKorad):
    assert isinstance(fake, SerialLike)


def test_send_writes_command_without_reading(transport: SerialTransport, fake: FakeKorad):
    transport.send(b"OUT1")
    assert fake.written == [b"OUT1"]
    assert fake.output is True


def test_query_returns_reply_bytes(transport: SerialTransport):
    assert transport.query(b"*IDN?") == b"KORAD RS3005P V2.0"


def test_query_flushes_stale_input_first(transport: SerialTransport, fake: FakeKorad):
    # Leave junk in the device's output buffer; a query must discard it before
    # writing so it reads only its own reply.
    fake._out.extend(b"STALE")
    assert transport.query(b"VSET1?") == b"00.00"


def test_close_marks_connection_closed(transport: SerialTransport):
    assert transport.is_open is True
    transport.close()
    assert transport.is_open is False
    transport.close()  # idempotent
