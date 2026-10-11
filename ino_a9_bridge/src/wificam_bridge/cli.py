"""Command-line inspection helpers."""

from __future__ import annotations

import argparse
import dataclasses
import json
from typing import Any

from .pprpc import PacketError, parse_packet


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, bytes):
        return {"length": len(value), "hex": value.hex()}
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect INO A9 PPRPC packets")
    commands = parser.add_subparsers(dest="command", required=True)
    decode = commands.add_parser("decode", help="decode one hexadecimal packet")
    decode.add_argument("hex_packet", help="packet bytes as hexadecimal")
    mode = decode.add_mutually_exclusive_group()
    mode.add_argument("--udp", action="store_true", help="require UDP Qp prefix")
    mode.add_argument("--tcp", action="store_true", help="treat input as TCP framing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = bytes.fromhex(args.hex_packet)
        udp = True if args.udp else False if args.tcp else None
        packet = parse_packet(data, udp=udp)
    except (ValueError, PacketError) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps(_jsonable(packet), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
