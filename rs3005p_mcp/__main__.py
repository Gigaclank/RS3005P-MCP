"""Console entry point: run the MCP server over stdio.

Optional safety configuration can be supplied on the command line and is mapped
onto the environment variables the server reads at connect time:

    rs3005p-mcp --profile devices.json --device 24v-sensor

Equivalent to launching with ``RS3005P_PROFILE`` / ``RS3005P_DEVICE`` set.
"""

from __future__ import annotations

import argparse
import os

from .server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="rs3005p-mcp")
    parser.add_argument(
        "--profile",
        help="Path to a device-profile (safety envelope) library file.",
    )
    parser.add_argument(
        "--device",
        help="Name of the attached device to select from the profile library.",
    )
    args = parser.parse_args()

    if args.profile:
        os.environ["RS3005P_PROFILE"] = args.profile
    if args.device:
        os.environ["RS3005P_DEVICE"] = args.device

    mcp.run()


if __name__ == "__main__":
    main()
