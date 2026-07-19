"""Session-aware splitting: the walk, the repair, and the disclosures (#27, ADR-0004).

No model runs in this tool, so a bad split cannot be caught here or downstream — these tests are
the only thing standing between a leaky partition and a silently invalidated evaluation. They pin
the four rules that make the split a promise rather than a hope: the Session is never torn, the
targets are computed once against a known ``N``, the order and the tie-breaks are total, and the
repair is the least-cost move that buys non-emptiness.

The disclosures are asserted as *data* — a move list, an overlap finding, an emptiness flag.
Rendering them is `summary.txt`'s job (#10), so nothing here asserts prose.
"""

import hashlib

import pytest

from sdw.config import SplitConfig
from sdw.ingest import Recording
from sdw.split import SPLIT_ORDER, RepairMove, _donor, _repair, split_sessions

DEFAULTS = SplitConfig()


def _recording(session_id: str, index: int, speaker_id: str = "spk_01") -> Recording:
    """One Recording, distinct by ``index``; only ``session_id``/``speaker_id`` matter here."""
    rid = f"sha256:{session_id}-{index}"
    return Recording(
        recording_id=rid,
        content_hash=rid,
        prompt_id=f"sha256:p{index}",
        path=f"{session_id}/{index}.wav",
        speaker_id=speaker_id,
        session_id=session_id,
        prompt_text=f"prompt {index}",
        device="mic",
        environment="quiet room",
    )


def _corpus(sizes: dict[str, int], speakers: dict[str, str] | None = None) -> list[Recording]:
    """``{session_id: sample_count}`` → the Recordings, optionally with a per-Session Speaker."""
    speakers = speakers or {}
    return [
        _recording(session_id, index, speakers.get(session_id, "spk_01"))
        for session_id, count in sizes.items()
        for index in range(count)
    ]


def _hash_order(session_ids: list[str], seed: int = DEFAULTS.seed) -> list[str]:
    """The ADR's ordering key, recomputed independently of the implementation."""
    return sorted(
        session_ids,
        key=lambda sid: hashlib.sha256(f"{seed}:{sid}".encode()).hexdigest(),
    )


# --- Grouping ------------------------------------------------------------------------------------


def test_a_session_lands_in_exactly_one_split() -> None:
    result = split_sessions(_corpus({f"sess_{i:02d}": 3 for i in range(7)}), DEFAULTS)

    assert set(result.assignments) == {f"sess_{i:02d}" for i in range(7)}
    assert set(result.assignments.values()) <= set(SPLIT_ORDER)


def test_every_recording_of_a_session_gets_that_session_s_split() -> None:
    recordings = _corpus({"sess_01": 4, "sess_02": 4, "sess_03": 4})
    result = split_sessions(recordings, DEFAULTS)

    for recording in recordings:
        assert result.split_of(recording) == result.assignments[recording.session_id]


def test_a_speaker_may_recur_across_splits() -> None:
    # Single-speaker data is v0.1's expected shape, so one Speaker filling all three splits is
    # the guarantee working, not a defect (ADR-0004).
    result = split_sessions(_corpus({f"sess_{i:02d}": 3 for i in range(4)}), DEFAULTS)

    assert set(result.assignments.values()) == set(SPLIT_ORDER)
    assert result.speaker_overlaps == ()


# --- Targets and deficits ------------------------------------------------------------------------


def test_targets_are_sample_counts_computed_once_against_the_total() -> None:
    result = split_sessions(_corpus({"sess_01": 5, "sess_02": 4, "sess_03": 3}), DEFAULTS)

    assert result.total_samples == 12
    assert result.targets == pytest.approx({"train": 9.6, "val": 1.2, "test": 1.2})


def test_deficits_are_floats_and_go_negative_on_overshoot() -> None:
    # One 10-Sample Session cannot fit val's 1.2-Sample target, so whichever split takes it
    # overshoots — the deficit must record that as a negative float, not clamp at zero.
    result = split_sessions(_corpus({"sess_01": 10, "sess_02": 1, "sess_03": 1}), DEFAULTS)

    assert any(deficit < 0 for deficit in result.deficits.values())
    assert all(isinstance(deficit, float) for deficit in result.deficits.values())


def test_deficits_are_never_rounded() -> None:
    result = split_sessions(_corpus({"sess_01": 1, "sess_02": 1, "sess_03": 1}), DEFAULTS)

    assert result.deficits["train"] == pytest.approx(0.8 * 3 - result.samples["train"])


# --- Order and tie-breaks ------------------------------------------------------------------------


def test_session_order_is_by_seeded_hash_not_by_session_id() -> None:
    sizes = {f"sess_{i:02d}": 1 for i in range(12)}
    result = split_sessions(_corpus(sizes), DEFAULTS)

    assert result.order == tuple(_hash_order(list(sizes)))
    assert result.order != tuple(sorted(sizes))


def test_a_different_seed_reorders_the_walk() -> None:
    sizes = {f"sess_{i:02d}": 1 for i in range(12)}
    other = SplitConfig(seed=7)

    assert split_sessions(_corpus(sizes), other).order == tuple(_hash_order(list(sizes), seed=7))
    assert (
        split_sessions(_corpus(sizes), other).order
        != split_sessions(_corpus(sizes), DEFAULTS).order
    )


def test_the_same_input_and_config_split_identically() -> None:
    sizes = {f"sess_{i:02d}": i + 1 for i in range(9)}

    assert split_sessions(_corpus(sizes), DEFAULTS) == split_sessions(_corpus(sizes), DEFAULTS)


def test_a_deficit_tie_breaks_by_split_order_not_hash_order() -> None:
    # Equal ratios and one Sample per Session: every step after the first is a three-way tie, so
    # the assignment cycles train → val → test in SPLIT_ORDER.
    thirds = SplitConfig(train=1 / 3, val=1 / 3, test=1 / 3)
    result = split_sessions(_corpus({f"sess_{i:02d}": 1 for i in range(3)}), thirds)

    assert [result.assignments[sid] for sid in result.order] == list(SPLIT_ORDER)


def test_assignment_goes_to_the_maximum_deficit() -> None:
    # 80-10-10 over equal one-Sample Sessions: train's 0.8-per-Sample target keeps it hungriest
    # for the first several Sessions, so it takes the majority.
    result = split_sessions(_corpus({f"sess_{i:02d}": 1 for i in range(10)}), DEFAULTS)

    assert result.samples["train"] == 8
    assert result.samples["val"] == 1
    assert result.samples["test"] == 1


# --- The repair ----------------------------------------------------------------------------------


def test_adr_0004_worked_example_lands_6_3_3() -> None:
    # 12 Samples / 4 Sessions x 3 / default 80-10-10 → water-filling leaves test empty, the repair
    # fires, and train (not the largest-surplus val, which holds one Session) donates its
    # first-in-hash-order Session. ADR-0004's table, asserted end to end.
    result = split_sessions(_corpus({f"sess_{i:02d}": 3 for i in range(4)}), DEFAULTS)

    assert result.samples == {"train": 6, "val": 3, "test": 3}
    assert result.sessions == {"train": 2, "val": 1, "test": 1}
    assert result.moves == (
        RepairMove(session_id=result.order[0], donor="train", recipient="test"),
    )
    assert result.empty_splits == ()


def test_the_donor_holds_at_least_two_sessions() -> None:
    # The worked example's load-bearing filter: val has the largest surplus but exactly one
    # Session, so donating it would merely relocate the emptiness.
    result = split_sessions(_corpus({f"sess_{i:02d}": 3 for i in range(4)}), DEFAULTS)
    (move,) = result.moves

    assert move.donor == "train"
    assert result.sessions[move.donor] >= 1


def test_the_moved_session_is_the_donor_s_smallest() -> None:
    # train ends up holding a 1-Sample and a 9-Sample Session; the repair must cost one Sample,
    # not nine.
    result = split_sessions(_corpus({"sess_01": 9, "sess_02": 1, "sess_03": 1}), DEFAULTS)
    moves = [m for m in result.moves if m.donor == "train"]

    for move in moves:
        assert move.session_id != "sess_01"


def test_no_repair_when_water_filling_already_fills_val_and_test() -> None:
    result = split_sessions(_corpus({f"sess_{i:02d}": 1 for i in range(10)}), DEFAULTS)

    assert result.moves == ()
    assert result.empty_splits == ()


def test_repair_never_runs_below_three_sessions() -> None:
    result = split_sessions(_corpus({"sess_01": 5, "sess_02": 5}), DEFAULTS)

    assert result.moves == ()


def test_val_is_repaired_before_test() -> None:
    # Both starved and both repairable: SPLIT_ORDER fixes val first, and state is recomputed
    # between the two moves.
    result = split_sessions(_corpus({f"sess_{i:02d}": 1 for i in range(3)}), DEFAULTS)

    assert [move.recipient for move in result.moves] == ["val", "test"]
    assert result.samples == {"train": 1, "val": 1, "test": 1}


# --- Fewer than three Sessions -------------------------------------------------------------------


def test_two_sessions_produce_and_flag_rather_than_abort() -> None:
    result = split_sessions(_corpus({"sess_01": 3, "sess_02": 3}), DEFAULTS)

    assert result.samples["train"] + result.samples["val"] + result.samples["test"] == 6
    assert result.empty_splits != ()
    assert set(result.empty_splits) <= {"val", "test"}


def test_one_session_fills_train_and_flags_val_and_test_empty() -> None:
    result = split_sessions(_corpus({"sess_01": 4}), DEFAULTS)

    assert result.assignments == {"sess_01": "train"}
    assert result.empty_splits == ("val", "test")


def test_no_recordings_at_all_is_an_empty_split_not_a_crash() -> None:
    result = split_sessions([], DEFAULTS)

    assert result.total_samples == 0
    assert result.assignments == {}
    assert result.empty_splits == SPLIT_ORDER


# --- Speaker-overlap disclosure ------------------------------------------------------------------


def test_multi_speaker_overlap_is_reported_as_a_finding() -> None:
    # One Speaker across two Sessions that land in different splits, plus a second Speaker so the
    # single-speaker suppression does not apply.
    recordings = _corpus(
        {"sess_01": 1, "sess_02": 1, "sess_03": 1},
        speakers={"sess_01": "spk_01", "sess_02": "spk_01", "sess_03": "spk_02"},
    )
    result = split_sessions(recordings, DEFAULTS)
    overlapped = {overlap.speaker_id for overlap in result.speaker_overlaps}

    assert overlapped == {"spk_01"}
    for overlap in result.speaker_overlaps:
        assert len(overlap.splits) > 1
        assert list(overlap.splits) == [s for s in SPLIT_ORDER if s in overlap.splits]


def test_a_speaker_confined_to_one_split_is_not_reported() -> None:
    recordings = _corpus(
        {"sess_01": 1, "sess_02": 1, "sess_03": 1},
        speakers={"sess_01": "spk_01", "sess_02": "spk_02", "sess_03": "spk_03"},
    )
    result = split_sessions(recordings, DEFAULTS)

    assert result.speaker_overlaps == ()


def test_single_speaker_data_suppresses_the_disclosure_entirely() -> None:
    result = split_sessions(_corpus({f"sess_{i:02d}": 2 for i in range(6)}), DEFAULTS)

    assert result.speaker_overlaps == ()


def test_overlaps_are_ordered_by_speaker_id() -> None:
    speakers = {"sess_01": "spk_02", "sess_02": "spk_02", "sess_03": "spk_01", "sess_04": "spk_01"}
    result = split_sessions(_corpus(dict.fromkeys(speakers, 1), speakers), DEFAULTS)
    reported = [overlap.speaker_id for overlap in result.speaker_overlaps]

    assert reported == sorted(reported)


def test_a_speaker_overlap_is_a_finding_not_a_change_to_the_split() -> None:
    sizes = {f"sess_{i:02d}": 2 for i in range(4)}
    speakers = {sid: f"spk_{i:02d}" for i, sid in enumerate(sizes)}
    with_speakers = split_sessions(_corpus(sizes, speakers), DEFAULTS)
    single_speaker = split_sessions(_corpus(sizes), DEFAULTS)

    assert with_speakers.assignments == single_speaker.assignments


# --- Purity --------------------------------------------------------------------------------------


def test_the_split_does_not_depend_on_recording_order() -> None:
    recordings = _corpus({f"sess_{i:02d}": i + 1 for i in range(6)})
    shuffled = list(reversed(recordings))

    assert split_sessions(shuffled, DEFAULTS) == split_sessions(recordings, DEFAULTS)


def test_ratios_shift_the_partition() -> None:
    sizes = {f"sess_{i:02d}": 1 for i in range(10)}
    test_heavy = SplitConfig(train=0.2, val=0.4, test=0.4)
    result = split_sessions(_corpus(sizes), test_heavy)

    assert result.samples["test"] > result.samples["train"]


def test_no_eligible_donor_is_a_no_op_rather_than_a_crash() -> None:
    # Unreachable through `split_sessions`: pigeonhole guarantees an eligible donor whenever there
    # are >= 3 Sessions and a split is starved, and below that the repair does not run. Asserted
    # directly because the guard's job is to keep a future ratio rule from turning a disclosure
    # into a traceback — the split is best-effort, and a repair it cannot make is not an error.
    one_per_split = {"sess_01": "train", "sess_02": "val", "sess_03": "test"}
    sizes = dict.fromkeys(one_per_split, 1)
    targets = {name: 1.0 for name in SPLIT_ORDER}

    assert _donor(one_per_split, sizes, targets) is None
    assert _repair(one_per_split, tuple(one_per_split), sizes, targets) == ()
