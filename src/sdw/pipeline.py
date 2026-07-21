"""The two commands' internals.

Every real stage has now landed. `validate` reads `recordings.csv` and resolves the Originals
(ingest, #24), decodes each and converts it to mono 16 kHz (normalize, #25), and measures each
Recording for its advisory flags (quality, #26) — then prints the digest and writes nothing,
anywhere (ADR-0002). `build` runs those same three and hands each measured Recording to
:mod:`sdw.staging`, which owns the `--data-out` tree while it is under construction: splitting,
which assigns every Session to exactly one Split (#27); images, two PNGs per Recording (#31);
reporting, `reports/quality.jsonl` and `reports/summary.txt` (#32); and the Manifest plus
`dataset.json` (#28/#29). `staging` asks `commit`, the one writer, to write `dataset.json` last as
the completeness sentinel and swap the tree into `--data-out` by rename (#30, ADR-0003, #64). A hard
error anywhere leaves the last good Dataset untouched and no build ever visible half-finished.

What is left here is what both commands share: the preflight, and the decode-once-feed-many loop.
"""

from collections.abc import Iterator
from pathlib import Path

from sdw import ingest, normalize, quality, staging
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
    """Transform `data_in` into `data_out` as one atomic commit (#30, ADR-0003).

    The pipeline's shape, and nothing else: preflight, open a staged tree, feed it each Recording as
    the audio comes off the decoder, finish. Where each artifact lands, when the splitter runs, and
    what an abort discards are :mod:`sdw.staging`'s — the decode loop is what `build` owns, because
    one decode is what feeds every consumer while the audio is still in hand (#31, #32).
    """
    resolved, recordings = _preflight(data_in, config)
    with staging.open(data_out) as tree:
        for recording, audio, metrics in _measured(data_in, recordings, resolved):
            tree.add(recording, audio, metrics)
        tree.finish(resolved)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in`, print the quality digest, and write nothing, anywhere (ADR-0002).

    Normalization runs here in full and the audio is discarded: `validate`'s promise is that a
    green run means `build` will not hit a hard error, so it has to decode every Original too.
    Quality flags are advisory and never affect the exit code — a flagged Recording still exits 0,
    because the operator curates by editing `recordings.csv`, not by the tool refusing to proceed.
    """
    resolved, recordings = _preflight(data_in, config)
    print(quality.render_digest(analyze(data_in, recordings, resolved)), end="")
