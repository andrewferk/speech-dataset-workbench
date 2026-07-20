"""Argument parsing for `python -m sdw`.

Two commands, and the mapping from an outcome to an exit code:

- success → 0
- a hard error → 1 (aborted; no durable output)
- a usage error → argparse's own non-zero exit
"""

import argparse
import sys
from pathlib import Path

from sdw import pipeline
from sdw.errors import HardError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # Fixed rather than derived: `python -m sdw` would otherwise report `__main__.py`.
        # `sdw` is the documented entry point, and both doors reach here (ADR-0014).
        prog="sdw",
        description="Turn a collection of prompted speech recordings into a validated, "
        "reproducible, versioned dataset.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    # Both commands read --data-in under a --config; only build writes.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-in", type=Path, required=True, help="Read-only input directory.")
    common.add_argument("--config", type=Path, help="TOML config overriding tool defaults.")

    build = subcommands.add_parser(
        "build",
        parents=[common],
        help="Build a Dataset Version from --data-in into --data-out.",
    )
    build.add_argument(
        "--data-out", type=Path, required=True, help="Output directory, replaced wholesale."
    )

    subcommands.add_parser(
        "validate",
        parents=[common],
        help="Preflight --data-in and print the quality digest. Writes nothing.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            pipeline.build(data_in=args.data_in, data_out=args.data_out, config=args.config)
        else:
            pipeline.validate(data_in=args.data_in, config=args.config)
    except HardError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
