"""The two commands' internals: the shared preflight and the decode-once-feed-many loop.

`validate` runs preflight + normalize + quality and writes nothing, anywhere (ADR-0002). `build`
runs the same three and hands each measured Recording to :mod:`sdw.staging`, which owns the
`--data-out` tree while it is under construction — splitting (#27), images (#31), reports (#32), the
Manifest and `dataset.json` (#28/#29) — and asks `commit` to write the sentinel last and swap the
tree in by rename (#30,
ADR-0003, #64). A hard error anywhere leaves the last good Dataset untouched and no build ever
visible half-finished.
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

    Config loading (with split-ratio validation, ADR-0004/0007, #23) and ingest both run here so
    `validate` aborts on the same `--data-in`/`--config` hard errors `build` would (#24) — the whole
    of what a green preflight promises. Config is loaded first, so a bad ratio aborts before any
    file is read.
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
    comfortably in memory. ADR-0005's decode gate fires here, and the quality tap reads the Original
    and the Normalized while both are in hand. It yields rather than returns so `build` gets the
    audio while still in hand (to render and write) while `analyze` keeps only the numbers — without
    either forcing a second decode or holding the whole Dataset in memory.
    """
    for recording in recordings:
        audio = normalize.normalize(data_in / recording.path)
        yield recording, audio, quality.measure(audio, config.quality)


def analyze(
    data_in: Path, recordings: list[Recording], config: Config
) -> list[tuple[str, QualityMetrics]]:
    """Normalize and measure every Recording, keeping only its metrics. Writes nothing.

    `validate`'s measuring half. It cannot render an Image by accident not because a flag is off,
    but because the only function it calls has nowhere to write to (ADR-0011).
    """
    return [
        (recording.recording_id, metrics)
        for recording, _, metrics in _measured(data_in, recordings, config)
    ]


def build(*, data_in: Path, data_out: Path, config: Path | None) -> None:
    """Transform `data_in` into `data_out` as one atomic commit (#30, ADR-0003).

    Preflight, open a staged tree, feed each Recording as its audio comes off the decoder, finish.
    Where each artifact lands, when the splitter runs, and what an abort discards are
    :mod:`sdw.staging`'s; the decode loop is what `build` owns, because one decode feeds every
    consumer while the audio is still in hand (#31, #32).
    """
    resolved, recordings = _preflight(data_in, config)
    with staging.open(data_out) as tree:
        for recording, audio, metrics in _measured(data_in, recordings, resolved):
            tree.add(recording, audio, metrics)
        tree.finish(resolved)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in`, print the quality digest, and write nothing, anywhere (ADR-0002).

    Normalization runs in full and the audio is discarded: a green `validate` promises `build` will
    not hit a hard error derivable from `--data-in` or `--config`, so it decodes every Original too.
    Quality flags are advisory — a flagged Recording still exits 0, because the operator curates by
    editing `recordings.csv`, not by the tool refusing to proceed (ADR-0007).
    """
    resolved, recordings = _preflight(data_in, config)
    print(quality.render_digest(analyze(data_in, recordings, resolved)), end="")
