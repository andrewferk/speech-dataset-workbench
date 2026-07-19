"""The two commands' internals.

Still partly stubs: they hold the shape (a pure function of `--data-in` plus config) and the
hard-error contract. Three real stages have landed — ingest, which reads `recordings.csv`, resolves
the Originals, and derives their identity (#24); normalization, which decodes each Original and
converts it to mono 16 kHz in memory (#25); and quality, which measures each Recording and derives
its advisory flags (#26). That completes `validate`, which now prints the quality digest. The
remaining stages — splitting, manifest, reports, images — land in later tickets, and all of them
are on the `build` side.
"""

from pathlib import Path

from sdw import ingest, normalize, quality
from sdw.config import Config, load_config
from sdw.errors import HardError
from sdw.ingest import Recording
from sdw.quality import QualityMetrics


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


def _normalize_and_measure(
    data_in: Path, recordings: list[Recording], config: Config
) -> list[tuple[str, QualityMetrics]]:
    """Normalize and measure every Recording, one at a time, keeping only its metrics (#25, #26).

    One Recording's audio is decoded at a time — a Dataset's worth of float64 does not fit
    comfortably in memory, and no stage needs more than one at once; only the seven numbers
    survive the iteration. Two things happen in this loop, and both must happen for *either*
    command: ADR-0005's decode gate fires here (a non-WAV, corrupt, truncated, or zero-frame
    Original aborts the run), and the quality tap reads the Original and the Normalized while both
    are in hand. Nothing here branches on a flag — measuring is all it does.
    """
    return [
        (
            recording.recording_id,
            quality.measure(normalize.normalize(data_in / recording.path), config.quality),
        )
        for recording in recordings
    ]


def build(*, data_in: Path, data_out: Path, config: Path | None) -> None:
    """Transform `data_in` into `data_out` as one atomic commit (ADR-0003)."""
    resolved, recordings = _preflight(data_in, config)
    # Measured but not yet written: `reports/quality.jsonl` and the `summary.txt` quality section
    # are the reporting ticket's (#27), which renders these same metrics.
    _normalize_and_measure(data_in, recordings, resolved)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in`, print the quality digest, and write nothing, anywhere (ADR-0002).

    Normalization runs here in full and the audio is discarded: `validate`'s promise is that a
    green run means `build` will not hit a hard error, so it has to decode every Original too.
    Quality flags are advisory and never affect the exit code — a flagged Recording still exits 0,
    because the operator curates by editing `recordings.csv`, not by the tool refusing to proceed.
    """
    resolved, recordings = _preflight(data_in, config)
    print(quality.render_digest(_normalize_and_measure(data_in, recordings, resolved)), end="")
