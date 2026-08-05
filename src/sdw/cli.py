"""Argument parsing for the `sdw` command.

Three commands, and the mapping from an outcome to an exit code:

- success → 0
- a hard error → 1 (aborted; no durable output)
- a usage error → argparse's own non-zero exit
"""

import argparse
import importlib.util
import sys
from pathlib import Path

from sdw.errors import HardError

# Every name the `asr` extra provides. All of them, not a sentinel: a half-installed venv is then
# diagnosed as a missing extra rather than crashing partway through the import (ADR-0023).
ASR_MODULES = ("torch", "transformers")

MISSING_ASR_EXTRA = (
    "sdw transcribe needs the ASR extra, which is not installed.\n"
    "       uv sync --extra asr        (in a checkout)\n"
    "       pip install 'sdw[asr]'     (installed)"
)


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

    # No `--config` and no Scope flag, not even an empty one for symmetry with `build`: zero knobs
    # is what makes a Hypothesis attributable, and an empty config section invites one (ADR-0017).
    # Neither path defaults — both are operator-named external paths (ADR-0002, ADR-0021).
    transcribe = subcommands.add_parser(
        "transcribe",
        help="Transcribe a built Dataset Version into a new Run under --eval-out.",
    )
    transcribe.add_argument(
        "--dataset", type=Path, required=True, help="Built Dataset Version, read-only."
    )
    transcribe.add_argument(
        "--eval-out", type=Path, required=True, help="Root that holds Runs; one is minted per call."
    )

    return parser


def _require_asr_extra() -> None:
    """Abort before anything under `sdw.transcribe` is imported when the extra is absent.

    A `find_spec` probe, never a caught `ImportError` (ADR-0023): a typo'd internal module name
    raises `ImportError` too, and reporting that as a missing extra sends the operator to fix the
    one thing that is not wrong. `find_spec` locates a module without executing it, so this is free.
    """
    if any(importlib.util.find_spec(name) is None for name in ASR_MODULES):
        raise HardError(MISSING_ASR_EXTRA)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Hoisting this import costs every branch's `--help` its load, not just this one
        # (ADR-0023).
        if args.command == "build":
            from sdw import pipeline

            pipeline.build(data_in=args.data_in, data_out=args.data_out, config=args.config)
        elif args.command == "transcribe":
            # The earliest preflight there is: ahead of the import below, and far ahead of the
            # structural aborts that are themselves in front of the model load (ADR-0023).
            _require_asr_extra()

            from sdw.transcribe import pipeline as transcribe_pipeline

            transcribe_pipeline.transcribe(dataset=args.dataset, eval_out=args.eval_out)
        else:
            from sdw import pipeline

            pipeline.validate(data_in=args.data_in, config=args.config)
    except HardError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
