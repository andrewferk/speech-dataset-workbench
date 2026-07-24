"""The `--data-out` tree while it is being built: what lands in it, and where (#64, ADR-0003).

:mod:`sdw.commit` owns *when* a tree becomes the Dataset — the `.tmp`/`.old` protocol, the sentinel
written last, the atomic swap. This module owns *what goes into* one, and is `commit`'s only caller.
Two invariants that used to be caller discipline are properties of the interface's shape:

- **An abort discards the staging.** It is the context manager's exit, catching `BaseException` so
  an interrupt is no different from a hard error; `finish` runs inside the scope, so a failure
  during the swap discards too.
- **The splitter runs on the fixed surviving set.** `finish` is the only thing that splits and it
  sees every Recording handed to `add`, so splitting early is not an ordering mistake a reader has
  to catch — it is not expressible (ADR-0004).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sdw import commit, images, manifest, normalize, provenance, reports, split
from sdw.config import Config
from sdw.ingest import Recording
from sdw.normalize import NormalizedAudio
from sdw.quality import QualityMetrics


@dataclass(frozen=True)
class _StagedRecording:
    """One added Recording: itself, what it measured, and where its WAV currently sits.

    Private on purpose: the three per-`recording_id` maps the pipeline used to thread (metrics,
    durations, flat WAV paths) collapsed into one record, and a fourth per-Recording fact is a field
    here rather than a fourth map somewhere else.
    """

    recording: Recording
    metrics: QualityMetrics
    wav: Path


class StagedTree:
    """A `--data-out` tree under construction, rooted at the staging sibling.

    Constructed by :func:`open` rather than directly: the tree only makes sense inside the scope
    that guarantees it is discarded on abort.
    """

    def __init__(self, root: Path, data_out: Path) -> None:
        self._root = root
        self._data_out = data_out
        self._staged: list[_StagedRecording] = []

    def add(self, recording: Recording, audio: NormalizedAudio, metrics: QualityMetrics) -> None:
        """Render ``recording``'s Images and write its WAV now, retaining what :meth:`finish` needs.

        Called once per Recording while its audio is in hand — a Dataset's worth of float64 does not
        fit in memory. The WAV is written flat under `audio/` (no Session has a Split yet) and moved
        into its bucket by :meth:`finish`; the metrics are retained for the report lines and each
        Sample's `duration`.
        """
        images.render(audio, metrics, recording, self._root / images.IMAGES_DIR)
        wav = self._root / manifest.AUDIO_DIR / f"{recording.recording_id}.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        normalize.write_normalized(audio, wav)
        self._staged.append(_StagedRecording(recording=recording, metrics=metrics, wav=wav))

    def finish(self, config: Config) -> None:
        """Split, report, place, build the Manifest, and ask `commit` to promote the tree.

        Takes the whole resolved Config: the splitter needs its ratios and seed, the Manifest and
        the provenance descriptor the rest. `durations` is derived from `measured` rather than a
        second walk of the records, so the Manifest's `duration` and the report line's `duration_s`
        cannot come from different reads.
        """
        recordings = [staged.recording for staged in self._staged]
        measured = [(staged.recording.recording_id, staged.metrics) for staged in self._staged]
        durations = {recording_id: metrics.duration_s for recording_id, metrics in measured}
        split_result = split.split_sessions(recordings, config.split)
        reports.write_reports(self._root / reports.REPORTS_DIR, measured, split_result)
        self._place_audio(split_result)
        dataset = manifest.build_dataset(recordings, split_result, durations, config)
        commit.write_files(self._root, dataset.files)
        descriptor = provenance.build_provenance(config, dataset)
        commit.commit(self._root, self._data_out, descriptor.files)

    def _place_audio(self, split_result: split.SplitResult) -> None:
        """Move each flat Normalized WAV into `audio/<split>/<recording_id>.wav` (ADR-0003/0006).

        A rename within the staging tree — one filesystem, no durable output touched. The bucketed
        path is the one the Manifest's `audio_filepath` records, so this is what makes that pointer
        true.
        """
        for staged in self._staged:
            target = self._root / manifest.audio_path(
                split_result.split_of(staged.recording), staged.recording.recording_id
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.wav.rename(target)


@contextmanager
def open(data_out: Path) -> Iterator[StagedTree]:
    """Yield a staged tree for ``data_out``, discarding the staging on any exception (ADR-0003).

    Only ever read as `staging.open`, so the builtin is not shadowed for any caller.
    `commit.prepare` clears the siblings a crashed run left behind. `BaseException` rather than
    `Exception`: an interrupt must leave the last good Dataset as intact as a hard error does. On
    success the staging has been renamed away by :meth:`StagedTree.finish`, so nothing is left to
    discard.
    """
    root = commit.prepare(data_out)
    try:
        yield StagedTree(root, data_out)
    except BaseException:
        commit.discard(root)
        raise
