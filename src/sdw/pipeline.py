"""The two commands' internals.

Stubs for now: they hold the shape (a pure function of `--data-in` plus config) and the
hard-error contract, and nothing else. The stages themselves — ingest, normalization, quality,
splitting, manifest, images — land in later tickets.
"""

from pathlib import Path

from sdw.config import Config, load_config
from sdw.errors import HardError


def _check_paths(data_in: Path, config: Path | None) -> None:
    if not data_in.is_dir():
        raise HardError(f"--data-in is not a directory: {data_in}")
    if config is not None and not config.is_file():
        raise HardError(f"--config is not a file: {config}")


def _preflight(data_in: Path, config: Path | None) -> Config:
    """Path and config checks shared by both commands.

    Config loading — including split-ratio validation (ADR-0004/0007, #23) — happens here so
    that `validate` aborts on an illegal ratio too. If it lived in the splitter (a later stage
    than `validate` reaches), a green preflight could not promise a hard-error-free `build`.
    """
    _check_paths(data_in, config)
    return load_config(config)


def build(*, data_in: Path, data_out: Path, config: Path | None) -> None:
    """Transform `data_in` into `data_out` as one atomic commit (ADR-0003)."""
    _preflight(data_in, config)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in` and print the quality digest. Writes nothing, anywhere (ADR-0002)."""
    _preflight(data_in, config)
