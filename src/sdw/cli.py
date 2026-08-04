"""Argument parsing for the `sdw` command.

The commands, and the mapping from an outcome to an exit code:

- success → 0
- a hard error → 1 (aborted; no durable output)
- a usage error → argparse's own non-zero exit
"""

import argparse
import sys
from pathlib import Path

from sdw.errors import HardError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        # Fixed, or `python -m sdw` reports `__main__.py`; `sdw` is the entry point (ADR-0014).
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

    # `score` shares nothing with the two dataset commands: no --data-in, no --config, and no
    # dataset argument of any kind — one Run directory and nothing else (ADR-0017/ADR-0018).
    score = subcommands.add_parser(
        "score",
        help="Score a Run directory and print the Evaluation Report to stdout. Writes nothing.",
    )
    score.add_argument("--run", type=Path, required=True, help="Run directory. Read-only.")
    score.add_argument(
        "--split",
        help="Evaluation Scope: one Split. Default: every Split present.",
    )
    score.add_argument(
        "--format",
        # The tokens `sdw.score.command.RENDERINGS` keys on; named here because the parser is built
        # before dispatch, and importing a command module to build it is what ADR-0023 forbids.
        choices=("text", "json"),
        default="text",
        help="Rendering of the one Report (default: text).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Hoisting this import costs every branch's `--help` its load, not just this one
        # (ADR-0023).
        if args.command == "build":
            from sdw import pipeline

            pipeline.build(data_in=args.data_in, data_out=args.data_out, config=args.config)
        elif args.command == "score":
            from sdw.score import command

            command.score(run_dir=args.run, split=args.split, output_format=args.format)
        else:
            from sdw import pipeline

            pipeline.validate(data_in=args.data_in, config=args.config)
    except HardError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
