"""MCP server for RS PRO RS-3005P / RS-6005P programmable DC power supplies.

The package is layered so that the protocol logic is independent of I/O and of
the MCP transport, which keeps each layer unit-testable in isolation:

* :mod:`rs3005p_mcp.models`    -- versioned hardware limits / value formatting.
* :mod:`rs3005p_mcp.protocol`  -- pure command encode / response decode.
* :mod:`rs3005p_mcp.transport` -- serial framing, locking and timing.
* :mod:`rs3005p_mcp.device`    -- high-level instrument operations + validation.
* :mod:`rs3005p_mcp.server`    -- the MCP tool surface.
"""

from .models import MODELS, PowerSupplyModel
from .protocol import PROTOCOL_VERSION, Status

__all__ = ["MODELS", "PowerSupplyModel", "PROTOCOL_VERSION", "Status"]
__version__ = "0.1.0"
