"""The two report artifacts (#32) — the record a build leaves of what it measured and decided.

These tests exist because `reports/quality.jsonl` and `reports/summary.txt` are the artifacts
ADR-0008 commits to comparing as exact goldens. A golden catches *change*; these catch the specific
promises the golden would otherwise silently re-baseline — key order, sort order, per-field
rounding, the unconditional split table, and the notes that must stay suppressed when they would be
noise.
"""

import json
from pathlib import Path

from sdw.config import SplitConfig
from sdw.ingest import Recording
from sdw.quality import QualityMetrics
from sdw.reports import (
    QUALITY_JSONL,
    QUALITY_KEYS,
    SUMMARY_TXT,
    _join,
    _overlap_note,
    _percent,
    render_quality_jsonl,
    render_summary,
    write_reports,
)
from sdw.split import SpeakerOverlap, SplitResult, split_sessions


def _metrics(*, duration_s: float = 4.0, flags: tuple[str, ...] = ()) -> QualityMetrics:
    return QualityMetrics(
        duration_s=duration_s,
        peak_dbfs=-0.512345,
        clip_ratio=0.00312345,
        active_rms_dbfs=-22.398765,
        leading_silence_s=0.3404,
        trailing_silence_s=0.1201,
        silence_ratio=0.081234,
        flags=flags,
    )


def _recording(recording_id: str, speaker_id: str, session_id: str) -> Recording:
    return Recording(
        recording_id=recording_id,
        content_hash="sha256:" + "0" * 64,
        prompt_id="prm_" + "0" * 16,
        path=f"{speaker_id}/{session_id}/{recording_id}.wav",
        speaker_id=speaker_id,
        session_id=session_id,
        prompt_text="hello",
        device="dev",
        environment="quiet",
    )


def _dataset(sessions: int, *, speakers: int = 1, per_session: int = 3) -> list[Recording]:
    """``sessions`` Sessions of ``per_session`` Recordings, dealt round-robin across speakers."""
    return [
        _recording(f"rec_{s:02d}{i:02d}", f"spk_{s % speakers:02d}", f"sess_{s:02d}")
        for s in range(sessions)
        for i in range(per_session)
    ]


def _split(recordings: list[Recording]) -> SplitResult:
    return split_sessions(recordings, SplitConfig())


class TestQualityJsonl:
    """One row per kept Recording, fixed key order, sorted by id (ADR-0007)."""

    def test_one_row_per_recording_including_clean_ones(self) -> None:
        results = [("rec_b", _metrics()), ("rec_a", _metrics(flags=("clipping",)))]
        rows = [json.loads(line) for line in render_quality_jsonl(results).splitlines()]
        assert [row["id"] for row in rows] == ["rec_a", "rec_b"]

    def test_key_order_is_fixed_not_insertion_dependent(self) -> None:
        line = render_quality_jsonl([("rec_a", _metrics())]).splitlines()[0]
        assert list(json.loads(line).keys()) == list(QUALITY_KEYS)

    def test_clean_recording_has_an_empty_flags_array(self) -> None:
        row = json.loads(render_quality_jsonl([("rec_a", _metrics())]).splitlines()[0])
        assert row["flags"] == []

    def test_flags_are_a_json_array_not_a_string(self) -> None:
        results = [("rec_a", _metrics(flags=("clipping", "low_volume")))]
        row = json.loads(render_quality_jsonl(results).splitlines()[0])
        assert row["flags"] == ["clipping", "low_volume"]

    def test_rounding_is_fixed_per_field_type(self) -> None:
        """dBFS 2 dp, ratios 4 dp, seconds 3 dp — so the file is an exact golden."""
        row = json.loads(render_quality_jsonl([("rec_a", _metrics())]).splitlines()[0])
        assert row["peak_dbfs"] == -0.51
        assert row["active_rms_dbfs"] == -22.4
        assert row["clip_ratio"] == 0.0031
        assert row["silence_ratio"] == 0.0812
        assert row["duration_s"] == 4.0
        assert row["leading_silence_s"] == 0.34
        assert row["trailing_silence_s"] == 0.12

    def test_input_order_does_not_change_the_bytes(self) -> None:
        results = [("rec_a", _metrics()), ("rec_b", _metrics(duration_s=1.0))]
        assert render_quality_jsonl(results) == render_quality_jsonl(list(reversed(results)))

    def test_every_line_is_newline_terminated(self) -> None:
        rendered = render_quality_jsonl([("rec_a", _metrics()), ("rec_b", _metrics())])
        assert rendered.endswith("\n")
        assert len(rendered.splitlines()) == 2

    def test_no_recordings_renders_an_empty_file(self) -> None:
        assert render_quality_jsonl([]) == ""


class TestSplitTable:
    """The target beside the realized count, on every build — no threshold, no conditional."""

    def test_table_prints_when_nothing_is_wrong(self) -> None:
        recordings = _dataset(4)
        summary = render_summary(
            [(r.recording_id, _metrics()) for r in recordings], _split(recordings)
        )
        assert "split" in summary
        for name in ("train", "val", "test"):
            assert f"\n{name}" in summary

    def test_target_and_realized_are_both_shown_with_percentages(self) -> None:
        """ADR-0004's worked example: 12 Samples over 4 equal Sessions, 80-10-10 configured."""
        recordings = _dataset(4)
        summary = render_summary([], _split(recordings))
        assert "9.6 (80%)" in summary
        assert "1.2 (10%)" in summary
        assert "(50%)" in summary and "(25%)" in summary


class TestRepairDisclosure:
    """One report-only line per repair move (ADR-0004)."""

    def test_each_move_is_disclosed_by_session_donor_and_recipient(self) -> None:
        recordings = _dataset(4)
        result = _split(recordings)
        summary = render_summary([], result)
        assert result.moves, "the worked example is expected to repair"
        for move in result.moves:
            assert (
                f"non-emptiness repair: moved session {move.session_id} "
                f"from {move.donor} to {move.recipient}" in summary
            )

    def test_no_repair_means_no_repair_lines(self) -> None:
        summary = render_summary([], _split(_dataset(1)))
        assert "non-emptiness repair" not in summary


class TestSpeakerOverlap:
    """Suppressed entirely for a single-speaker Dataset (ADR-0004)."""

    def test_suppressed_for_a_single_speaker(self) -> None:
        summary = render_summary([], _split(_dataset(4, speakers=1)))
        assert "speaker-independent" not in summary

    def test_noted_when_a_speaker_spans_splits_and_others_exist(self) -> None:
        recordings = _dataset(4, speakers=2)
        result = _split(recordings)
        summary = render_summary([], result)
        assert result.speaker_overlaps, "two speakers over three splits must overlap"
        for overlap in result.speaker_overlaps:
            assert f"Speaker {overlap.speaker_id} appears in" in summary
        assert "is not speaker-independent" in summary

    def test_two_splits_name_the_second_as_compromised(self) -> None:
        """ADR-0004's own wording: "appears in train and test — test set is not …"."""
        note = _overlap_note(SpeakerOverlap(speaker_id="spk_02", splits=("train", "test")))
        assert note == (
            "Speaker spk_02 appears in train and test — test set is not speaker-independent"
        )

    def test_a_speaker_spanning_all_three_compromises_more_than_the_last(self) -> None:
        """Naming only `test` would tell an operator their validation set was clean."""
        note = _overlap_note(SpeakerOverlap(speaker_id="spk_02", splits=("train", "val", "test")))
        assert note.endswith("val and test sets are not speaker-independent")


class TestMinSessionsWarning:
    """Below three Sessions the warning appears in both sections of the summary (ADR-0004)."""

    def test_warning_appears_in_both_the_quality_and_split_sections(self) -> None:
        summary = render_summary([("rec_a", _metrics())], _split(_dataset(2)))
        assert summary.count("WARNING:") == 2
        # One before the quality tally, one in the split section after the table.
        assert summary.index("WARNING:") < summary.index("Quality:")
        assert summary.rindex("WARNING:") > summary.index("split")

    def test_absent_at_three_or_more_sessions(self) -> None:
        assert "WARNING:" not in render_summary([], _split(_dataset(3)))


class TestDeterminism:
    """No wall-clock, no host facts — ADR-0008's golden comparison depends on it."""

    def test_rendering_twice_is_byte_identical(self) -> None:
        recordings = _dataset(4, speakers=2)
        results = [(r.recording_id, _metrics(flags=("clipping",))) for r in recordings]
        first = render_summary(results, _split(recordings))
        assert first == render_summary(results, _split(recordings))

    def test_jsonl_rendering_twice_is_byte_identical(self) -> None:
        results = [("rec_a", _metrics()), ("rec_b", _metrics(flags=("low_volume",)))]
        assert render_quality_jsonl(results) == render_quality_jsonl(results)


class TestFormattingHelpers:
    """The two guards that keep the table and the note readable at their edges."""

    def test_percent_of_an_empty_dataset_is_zero_not_a_division_error(self) -> None:
        assert _percent(0.0, 0) == "0%"

    def test_a_single_split_name_is_not_given_a_dangling_conjunction(self) -> None:
        assert _join(("train",)) == "train"

    def test_three_splits_read_as_prose(self) -> None:
        assert _join(("train", "val", "test")) == "train, val and test"


class TestWriteReports:
    """Both artifacts land in the staging tree under their spec'd names (ADR-0003)."""

    def test_writes_both_files(self, tmp_path: Path) -> None:
        recordings = _dataset(4)
        results = [(r.recording_id, _metrics()) for r in recordings]
        directory = tmp_path / "reports"
        write_reports(directory, results, _split(recordings))

        assert (directory / QUALITY_JSONL).read_text(encoding="utf-8") == render_quality_jsonl(
            results
        )
        assert (directory / SUMMARY_TXT).read_text(encoding="utf-8").startswith("Quality:")
