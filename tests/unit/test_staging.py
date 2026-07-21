"""The staged `--data-out` tree: what lands in it, where, and what an abort leaves (#64).

These are the assertions that previously needed a whole `build` and a committed tree to make. The
module owns the `--data-out` layout while it is under construction, so its interface is where the
placement claims belong: a Recording's Normalized audio under its assigned Split, `images/` a 1:1
mirror of what was added, one quality line per added Recording, and — the invariant the caller used
to carry as a `try`/`except` — no staging tree surviving an exception raised inside the scope.

The splitter is asserted at the same seam for the reason it moved here: `staging` holds every
Recording passed to `add`, so it cannot structurally run on anything but the fixed surviving set
(ADR-0004). A test that pinned *when* the call happens would be asserting statement order; this one
asserts *what it sees*, which is the property the ordering exists to produce.

Nothing here names the private per-Recording record. Collapsing three keyed maps into one is the
point of the change, and a test that knew its shape would re-export the thing that was removed.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from sdw import normalize, quality, split, staging
from sdw.commit import STAGING_SUFFIX
from sdw.config import SplitConfig, load_config
from sdw.images import IMAGES_DIR, SPECTROGRAM_SUFFIX, WAVEFORM_SUFFIX
from sdw.ingest import Recording
from sdw.manifest import AUDIO_DIR, audio_path
from sdw.normalize import NormalizedAudio
from sdw.reports import QUALITY_JSONL, REPORTS_DIR
from sdw.split import SplitResult
from tests import synth

CONFIG = load_config(None)


def _recording(index: int) -> Recording:
    """One Recording, its own Session so all three Splits can fill; ids are path-shaped."""
    return Recording(
        recording_id=f"rec_{index:016x}",
        content_hash=f"{index:064x}",
        prompt_id=f"{index:064x}",
        path=f"r{index}.wav",
        speaker_id="spk_01",
        session_id=f"sess_{index}",
        prompt_text=f"Line {index}.",
        device="mic",
        environment="quiet room",
    )


def _audio(root: Path, index: int) -> NormalizedAudio:
    """A real decoded tone — this module writes WAVs and renders PNGs, so stub audio will not do."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"r{index}.wav"
    synth.write_wav(
        path,
        freq_hz=300.0 + 50 * index,
        amp_dbfs=-18.0,
        duration_s=0.5 + 0.1 * index,
        sample_rate=16000,
        bit_depth=16,
        channels=1,
    )
    return normalize.normalize(path)


def _add(tree: staging.StagedTree, source: Path, index: int) -> Recording:
    """Measure and add one Recording, exactly as the pipeline's decode loop does."""
    recording = _recording(index)
    audio = _audio(source, index)
    tree.add(recording, audio, quality.measure(audio, CONFIG.quality))
    return recording


def _committed(tmp_path: Path, count: int) -> tuple[Path, list[Recording]]:
    """Open a tree, add ``count`` Recordings, finish it. Returns the committed `--data-out`."""
    data_out = tmp_path / "out"
    with staging.open(data_out) as tree:
        recordings = [_add(tree, tmp_path / "src", index) for index in range(count)]
        tree.finish(CONFIG)
    return data_out, recordings


def _staging_dir(data_out: Path) -> Path:
    """The sibling the tree is built in, named from `commit`'s constant rather than restated."""
    return data_out.with_name(data_out.name + STAGING_SUFFIX)


def _split_of(recordings: list[Recording]) -> SplitResult:
    """The assignment recomputed independently, so placement is checked against the contract."""
    return split.split_sessions(recordings, CONFIG.split)


class TestAudioPlacement:
    """Every Recording's Normalized audio lands under the Split it was assigned."""

    def test_each_recording_is_under_its_assigned_split(self, tmp_path: Path) -> None:
        data_out, recordings = _committed(tmp_path, 6)
        result = _split_of(recordings)
        for recording in recordings:
            expected = data_out / audio_path(result.split_of(recording), recording.recording_id)
            assert expected.is_file()

    def test_no_wav_is_left_flat_under_audio(self, tmp_path: Path) -> None:
        # The write-flat-then-rename dance is an implementation detail; a WAV directly under
        # `audio/` would mean a Recording never reached its bucket, and the Manifest's
        # `audio_filepath` would point at nothing.
        data_out, _ = _committed(tmp_path, 6)
        assert [p for p in (data_out / AUDIO_DIR).iterdir() if p.is_file()] == []

    def test_the_committed_wavs_are_exactly_the_added_recordings(self, tmp_path: Path) -> None:
        data_out, recordings = _committed(tmp_path, 4)
        found = {p.stem for p in (data_out / AUDIO_DIR).rglob("*.wav")}
        assert found == {recording.recording_id for recording in recordings}


class TestImages:
    """`images/` is a one-to-one mirror of what was added, asserted at this seam (ADR-0011)."""

    @pytest.mark.parametrize("count", [1, 3])
    def test_two_pngs_per_added_recording_and_nothing_else(
        self, tmp_path: Path, count: int
    ) -> None:
        data_out, recordings = _committed(tmp_path, count)
        expected = {
            f"{recording.recording_id}{suffix}"
            for recording in recordings
            for suffix in (WAVEFORM_SUFFIX, SPECTROGRAM_SUFFIX)
        }
        assert {p.name for p in (data_out / IMAGES_DIR).iterdir()} == expected


class TestReports:
    """N added Recordings produce N quality lines — testable without the CLI."""

    @pytest.mark.parametrize("count", [1, 5])
    def test_one_quality_line_per_added_recording(self, tmp_path: Path, count: int) -> None:
        data_out, recordings = _committed(tmp_path, count)
        lines = (data_out / REPORTS_DIR / QUALITY_JSONL).read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["id"] for line in lines] == sorted(
            recording.recording_id for recording in recordings
        )


class TestAbort:
    """An exception inside the scope discards the staging — the caller cannot forget to.

    What a *pre-existing* `--data-out` survives, and what a crashed run's leftovers do to the next
    one, stay in the end-to-end suite: those are claims about `--data-out` after a real run, and
    asserting them against the staged tree alone would be the weaker claim.
    """

    def test_an_exception_inside_the_scope_leaves_no_staging_directory(
        self, tmp_path: Path
    ) -> None:
        data_out = tmp_path / "out"
        with pytest.raises(RuntimeError, match="stage exploded"), staging.open(data_out) as tree:
            _add(tree, tmp_path / "src", 0)
            raise RuntimeError("stage exploded")
        assert not data_out.exists()
        assert not _staging_dir(data_out).exists()

    def test_a_keyboard_interrupt_discards_too(self, tmp_path: Path) -> None:
        # `BaseException`, not `Exception`: an interrupted build must not leave a staging tree
        # behind any more than a hard error does.
        data_out = tmp_path / "out"
        with pytest.raises(KeyboardInterrupt), staging.open(data_out) as tree:
            _add(tree, tmp_path / "src", 0)
            raise KeyboardInterrupt
        assert not _staging_dir(data_out).exists()


class TestSplitterInput:
    """The splitter observes every added Recording and only those (ADR-0004).

    *What* it sees, not when it is called: the ordering ADR-0004 cares about — that the surviving
    set is fixed before any Session is placed — shows up here as the set the splitter is handed,
    which is the property the ordering exists to produce.
    """

    def test_the_splitter_sees_exactly_the_added_recordings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Recording] = []
        real = split.split_sessions

        def spy(recordings: Sequence[Recording], config: SplitConfig) -> SplitResult:
            seen.extend(recordings)
            return real(recordings, config)

        monkeypatch.setattr(split, "split_sessions", spy)
        _, added = _committed(tmp_path, 4)
        assert [recording.recording_id for recording in seen] == [
            recording.recording_id for recording in added
        ]
