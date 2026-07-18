"""The two commands' internals.

Mostly stubs still: they hold the shape (a pure function of `--data-in` plus config) and the
hard-error contract. Two real stages have landed — ingest, which reads `recordings.csv`, resolves
the Originals, and derives their identity (#24), and normalization, which decodes each Original and
converts it to mono 16 kHz in memory (#25). The remaining stages — quality, splitting, manifest,
images — land in later tickets.
"""

from collections.abc import Iterator
from pathlib import Path

from sdw import ingest, normalize
from sdw.config import Config, load_config
from sdw.errors import HardError
from sdw.ingest import Recording
from sdw.normalize import NormalizedAudio


def _check_paths(data_in: Path, config: Path | None) -> None:
    if not data_in.is_dir():
        raise HardError(f"--data-in is not a directory: {data_in}")
    if config is not None and not config.is_file():
        raise HardError(f"--config is not a file: {config}")


def _preflight(data_in: Path, config: Path | None) -> tuple[Config, list[Recording]]:
    """Path checks, config loading, and ingest — everything both commands share.

    Config loading — including split-ratio validation (ADR-0004/0007, #23) — happens here so
    that `validate` aborts on an illegal ratio too. If it lived in the splitter (a later stage
    than `validate` reaches), a green preflight could not promise a hard-error-free `build`. Ingest
    runs here for the same reason: `recordings.csv` structural failures (#24) must abort `validate`,
    not just `build`. Config is loaded first so a bad ratio aborts before any file is read.
    """
    _check_paths(data_in, config)
    resolved = load_config(config)
    recordings = ingest.read_recordings(data_in)
    return resolved, recordings


def _normalized(data_in: Path, recordings: list[Recording]) -> Iterator[NormalizedAudio]:
    """Normalize each Recording's Original in memory, one at a time (#25, ADR-0005).

    Lazy on purpose: a Dataset's worth of decoded float64 does not fit comfortably in memory, and no
    stage needs more than one Recording's audio at a time. Later tickets hang the quality tap and
    the `--data-out` write off this same loop; today both commands just drain it, which is enough to
    fire the decode gate — a non-WAV, corrupt, truncated, or zero-frame Original aborts the run.
    """
    for recording in recordings:
        yield normalize.normalize(data_in / recording.path)


def build(*, data_in: Path, data_out: Path, config: Path | None) -> None:
    """Transform `data_in` into `data_out` as one atomic commit (ADR-0003)."""
    _, recordings = _preflight(data_in, config)
    for _audio in _normalized(data_in, recordings):
        pass  # Writing the Normalized WAVs into --data-out is the storage-layout ticket's job.


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in` and print the quality digest. Writes nothing, anywhere (ADR-0002).

    Normalization runs here in full and the result is discarded: `validate`'s promise is that a
    green run means `build` will not hit a hard error, so it has to decode every Original too.
    """
    _, recordings = _preflight(data_in, config)
    for _audio in _normalized(data_in, recordings):
        pass
