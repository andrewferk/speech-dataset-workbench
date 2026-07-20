"""The two commands' internals.

Every real stage has now landed. `validate` reads `recordings.csv` and resolves the Originals
(ingest, #24), decodes each and converts it to mono 16 kHz (normalize, #25), and measures each
Recording for its advisory flags (quality, #26) — then prints the digest and writes nothing,
anywhere (ADR-0002). `build` runs those same three and then the four that produce a durable tree:
splitting, which assigns every Session to exactly one Split (#27); images, two PNGs per Recording
(#31); reporting, `reports/quality.jsonl` and `reports/summary.txt` (#32); and the Manifest plus
`dataset.json` (#28/#29). It stages the whole tree into a sibling `.tmp` and hands it to `commit`,
the one writer, which writes `dataset.json` last as the completeness sentinel and swaps the tree
into `--data-out` by rename (#30, ADR-0003). A hard error anywhere leaves the last good Dataset
untouched and no build ever visible half-finished.
"""

from collections.abc import Iterator
from pathlib import Path

from sdw import commit, images, ingest, manifest, normalize, provenance, quality, reports, split
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

    The whole tree is staged into a sibling `<data-out>.tmp` — `commit.prepare` first clears any
    `.tmp`/`.old` a crashed run left behind — and nothing touches `--data-out` until the swap. On a
    hard error anywhere, `commit.discard` drops the staging and the last good Dataset is preserved
    byte for byte; the exit code is the CLI's. On success `commit.commit` writes `dataset.json`
    last, as the completeness sentinel, and renames the staged tree into place.
    """
    resolved, recordings = _preflight(data_in, config)
    staging = commit.prepare(data_out)
    try:
        # One decode feeds three consumers while the audio is in hand: the renderer (#31), the WAV
        # written into the staged tree, and the quality tap. The audio is never retained past its
        # iteration — a Dataset's worth of float64 does not fit in memory — so the Normalized WAV
        # is written now, to a flat path under `audio/`, and moved into its Split bucket below once
        # the assignment is known. The metrics *are* retained: they are the report lines (#32) and
        # each Recording's Manifest `duration`.
        measured: list[tuple[str, QualityMetrics]] = []
        durations: dict[str, float] = {}
        staged_audio: dict[str, Path] = {}
        for recording, audio, metrics in _measured(data_in, recordings, resolved):
            images.render(audio, metrics, recording, staging / "images")
            wav = staging / manifest.AUDIO_DIR / f"{recording.recording_id}.wav"
            wav.parent.mkdir(parents=True, exist_ok=True)
            normalize.write_normalized(audio, wav)
            staged_audio[recording.recording_id] = wav
            durations[recording.recording_id] = metrics.duration_s
            measured.append((recording.recording_id, metrics))
        # The splitter runs after normalize + validate on the fixed surviving set (ADR-0004), so
        # its position here is the contract, not a detail: a hard error must abort *before* any
        # Session is placed. That is why it follows the loop above rather than sharing it — the
        # loop is where every decode gate fires (#27). The Manifest (#28) consumes the assignments;
        # the reports render the disclosures it carries.
        split_result = split.split_sessions(recordings, resolved.split)
        reports.write_reports(staging / reports.REPORTS_DIR, measured, split_result)
        _place_audio(staging, staged_audio, recordings, split_result)
        dataset = manifest.build_dataset(recordings, split_result, durations, resolved)
        commit.write_files(staging, dataset.files)
        descriptor = provenance.build_provenance(resolved, dataset)
        # The commit is inside the `try` so a failure *within* it — the file-as-`--data-out`
        # abort, or an interrupted swap — discards the staging too. On success the staging has
        # been renamed away, so the `except` never fires and there is nothing left to discard.
        commit.commit(staging, data_out, descriptor.files)
    except BaseException:
        commit.discard(staging)
        raise


def _place_audio(
    staging: Path,
    staged_audio: dict[str, Path],
    recordings: list[Recording],
    split_result: split.SplitResult,
) -> None:
    """Move each flat Normalized WAV into `audio/<split>/<recording_id>.wav` (ADR-0003/0006).

    The WAVs were written flat during the decode loop, before any Session had a Split; once the
    assignment is known each is renamed into its Split bucket — a rename within the staging tree, so
    it stays on one filesystem and touches no durable output. The bucketed path is the one the
    Manifest's `audio_filepath` records, so this is what makes the pointer true.
    """
    for recording in recordings:
        target = staging / manifest.audio_path(
            split_result.split_of(recording), recording.recording_id
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        staged_audio[recording.recording_id].rename(target)


def validate(*, data_in: Path, config: Path | None) -> None:
    """Preflight `data_in`, print the quality digest, and write nothing, anywhere (ADR-0002).

    Normalization runs here in full and the audio is discarded: `validate`'s promise is that a
    green run means `build` will not hit a hard error, so it has to decode every Original too.
    Quality flags are advisory and never affect the exit code — a flagged Recording still exits 0,
    because the operator curates by editing `recordings.csv`, not by the tool refusing to proceed.
    """
    resolved, recordings = _preflight(data_in, config)
    print(quality.render_digest(analyze(data_in, recordings, resolved)), end="")
