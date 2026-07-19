"""The two commands' internals.

Still partly stubs: they hold the shape (a pure function of `--data-in` plus config) and the
hard-error contract. Five real stages have landed — ingest, which reads `recordings.csv`, resolves
the Originals, and derives their identity (#24); normalization, which decodes each Original and
converts it to mono 16 kHz in memory (#25); quality, which measures each Recording and derives its
advisory flags (#26); splitting, which assigns every Session to exactly one Split (#27); and
images, which renders two PNGs per Recording (#31). The first three complete `validate`, which
prints the quality digest and still writes nothing, anywhere. Splitting and images are `build`-only
— images are why `build` stages and commits a tree at all. The remaining stages — the manifest,
`dataset.json`, the reports — are later tickets, and all of them are on the `build` side too.
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

from sdw import images, ingest, normalize, quality, split
from sdw.config import Config, load_config
from sdw.errors import HardError
from sdw.ingest import Recording
from sdw.normalize import NormalizedAudio
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


def _measured(
    data_in: Path, recordings: list[Recording], config: Config
) -> Iterator[tuple[Recording, NormalizedAudio, QualityMetrics]]:
    """Yield each Recording with its Normalized audio and its metrics, one at a time (#25, #26).

    One Recording's audio is decoded at a time — a Dataset's worth of float64 does not fit
    comfortably in memory, and no stage needs more than one at once. Two things happen per
    iteration, and both must happen for *either* command: ADR-0005's decode gate fires here (a
    non-WAV, corrupt, truncated, or zero-frame Original aborts the run), and the quality tap reads
    the Original and the Normalized while both are in hand. Nothing here branches on a flag —
    measuring is all it does.

    It yields rather than returns because `build` needs the audio while it is still in hand — to
    render (#31) and, later, to write — while `analyze` wants only the numbers. A list of metrics
    would force `build` to decode a second time; a list of audio would hold the whole Dataset in
    memory. Neither caller decides what the other gets.
    """
    for recording in recordings:
        audio = normalize.normalize(data_in / recording.path)
        yield recording, audio, quality.measure(audio, config.quality)


def analyze(
    data_in: Path, recordings: list[Recording], config: Config
) -> list[tuple[str, QualityMetrics]]:
    """Normalize and measure every Recording, keeping only its metrics. Writes nothing.

    `validate`'s whole body, and the reason `validate` cannot render an Image by accident: it is
    not that a flag is off, it is that the only function it calls has nowhere to write to
    (ADR-0011).
    """
    return [
        (recording.recording_id, metrics)
        for recording, _, metrics in _measured(data_in, recordings, config)
    ]


def build(*, data_in: Path, data_out: Path, config: Path | None) -> None:
    """Transform `data_in` into `data_out` as one atomic commit (ADR-0003).

    The tree is staged into a sibling `<data-out>.tmp` and committed by rename, so a hard error
    anywhere leaves no durable output and no build is ever visible half-finished. The staging tree
    currently holds `images/` only — splitting runs here but writes nothing yet; the remaining
    stages — the manifest, `dataset.json`, the reports — fill it in, and #30 takes ownership of the
    commit itself, including `dataset.json` as the completeness sentinel.
    """
    resolved, recordings = _preflight(data_in, config)
    staging = data_out.with_name(data_out.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        # Measured but not yet written: `reports/quality.jsonl` and the `summary.txt` quality
        # section are the reporting ticket's (#32), which renders these same metrics.
        for recording, audio, metrics in _measured(data_in, recordings, resolved):
            images.render(audio, metrics, recording, staging / "images")
        # Likewise computed but not yet written. The splitter runs after normalize + validate on
        # the fixed surviving set (ADR-0004), so its position here is the contract, not a detail:
        # a hard error must abort *before* any Session is placed. That is why it follows the loop
        # above rather than sharing it — the loop is where every decode gate fires (#27). The
        # manifest (#12) consumes the assignments and `summary.txt` (#10) renders the disclosures
        # it carries.
        split.split_sessions(recordings, resolved.split)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _commit(staging, data_out)


def _commit(staging: Path, data_out: Path) -> None:
    """Swap the staged tree into place: the closest thing to atomic that is portable (ADR-0003).

    The only window without a live `--data-out` is the sub-millisecond gap between the two renames,
    and it is recoverable by re-running, since the build is deterministic and idempotent.
    """
    staging.mkdir(parents=True, exist_ok=True)
    previous = data_out.with_name(data_out.name + ".old")
    shutil.rmtree(previous, ignore_errors=True)
    if data_out.exists():
        data_out.rename(previous)
    staging.rename(data_out)
    shutil.rmtree(previous, ignore_errors=True)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in`, print the quality digest, and write nothing, anywhere (ADR-0002).

    Normalization runs here in full and the audio is discarded: `validate`'s promise is that a
    green run means `build` will not hit a hard error, so it has to decode every Original too.
    Quality flags are advisory and never affect the exit code — a flagged Recording still exits 0,
    because the operator curates by editing `recordings.csv`, not by the tool refusing to proceed.
    """
    resolved, recordings = _preflight(data_in, config)
    print(quality.render_digest(analyze(data_in, recordings, resolved)), end="")
