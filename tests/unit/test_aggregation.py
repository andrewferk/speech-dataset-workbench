"""Pooled, Macro-average and the five Breakdowns over a Scope of scored Samples (ADR-0018).

Every expected value is computed by hand from the normalized strings each case names, so a failure
says whether the grouping moved or the arithmetic under it did. The per-Sample counts these
aggregate are `tests/unit/test_metrics.py`'s business and are not re-derived here.
"""

from dataclasses import fields

import pytest

from sdw.errors import HardError
from sdw.score.aggregate import (
    Aggregation,
    Breakdown,
    Group,
    Macro,
    MacroStatistic,
    Pooled,
    ScoredSample,
    aggregate,
    scored,
)
from sdw.score.alignment import Alignment
from sdw.score.text_normalization import TIER_A, TIER_B

_EMPTY = Alignment(0, 0, 0, 0)


def _sample(
    reference: str,
    hypothesis: str,
    *,
    id: str = "s",
    split: str = "train",
    session_id: str = "sess-1",
    prompt_id: str = "p-1",
    device: str = "mic-a",
    environment: str = "room-a",
) -> ScoredSample:
    return scored(
        id=id,
        reference=reference,
        hypothesis=hypothesis,
        split=split,
        session_id=session_id,
        prompt_id=prompt_id,
        device=device,
        environment=environment,
    )


def _breakdown(aggregation: Aggregation, attribute: str) -> Breakdown:
    return next(b for b in aggregation.breakdowns if b.attribute == attribute)


def _group(aggregation: Aggregation, attribute: str, value: str) -> Group:
    return next(g for g in _breakdown(aggregation, attribute).groups if g.value == value)


class TestPooled:
    """Errors summed and Reference lengths summed, divided once — at every level (ADR-0018)."""

    def test_scope_pools_rather_than_averaging_per_sample_rates(self) -> None:
        # `a b c d` with one wrong token, then `e` with one wrong token: Pooled is 2/5 = 0.4, while
        # the mean of the two per-Sample rates (0.25, 1.0) would be 0.625.
        aggregation = aggregate(
            [
                _sample("a b c d", "a b c x", id="1"),
                _sample("e", "x", id="2"),
            ]
        )
        pooled = aggregation.pooled[TIER_A]
        assert pooled.words == (2, 0, 0, 5)
        assert pooled.word_error_rate == 0.4

    def test_group_pools_the_same_way(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b c d", "a b c x", id="1", session_id="sess-1"),
                _sample("e", "x", id="2", session_id="sess-1"),
                _sample("f", "f", id="3", session_id="sess-2"),
            ]
        )
        assert _group(aggregation, "session", "sess-1").pooled[TIER_A].word_error_rate == 0.4
        assert _group(aggregation, "session", "sess-2").pooled[TIER_A].word_error_rate == 0.0

    def test_character_level_is_its_own_alignment(self) -> None:
        # `ab cd` against `ab xd`: one substitution over five characters, the space included.
        aggregation = aggregate([_sample("ab cd", "ab xd")])
        pooled = aggregation.pooled[TIER_A]
        assert pooled.characters == (1, 0, 0, 5)
        assert pooled.character_error_rate == 0.2

    def test_sentence_error_rate_is_errors_over_pairs(self) -> None:
        aggregation = aggregate(
            [
                _sample("a", "a", id="1"),
                _sample("b", "x", id="2"),
                _sample("c", "x", id="3"),
                _sample("d", "x", id="4"),
            ]
        )
        pooled = aggregation.pooled[TIER_A]
        assert (pooled.sentence_errors, pooled.samples) == (3, 4)
        assert pooled.sentence_error_rate == 0.75

    def test_both_tiers_are_pooled(self) -> None:
        # `Um.` normalizes to `um` under Tier A and to `""` under Tier B, so the two tiers pool
        # different denominators over the identical Sample set (ADR-0018).
        aggregation = aggregate([_sample("Um. Hello", "Hello")])
        assert aggregation.pooled[TIER_A].words == (0, 1, 0, 2)
        assert aggregation.pooled[TIER_B].words == (0, 0, 0, 1)


class TestMacro:
    """Mean, standard deviation and median across a Breakdown's groups, over each group's Pooled."""

    def test_macro_averages_group_pooled_rates_not_sample_rates(self) -> None:
        # `sess-1` pools 2/5 = 0.4 over two Samples; `sess-2` pools 0/1 = 0.0 over one. Macro is the
        # unweighted mean of those two group rates, 0.2 — not the Pooled 2/6 the Scope reports.
        aggregation = aggregate(
            [
                _sample("a b c d", "a b c x", id="1", session_id="sess-1"),
                _sample("e", "x", id="2", session_id="sess-1"),
                _sample("f", "f", id="3", session_id="sess-2"),
            ]
        )
        macro = _breakdown(aggregation, "session").macro[TIER_A]
        assert macro.word_error_rate.mean == 0.2
        assert aggregation.pooled[TIER_A].word_error_rate == pytest.approx(2 / 6)

    def test_standard_deviation_and_median(self) -> None:
        # Group rates 0.0, 0.5, 1.0: population SD is sqrt(1/6), median is the middle value.
        aggregation = aggregate(
            [
                _sample("a b", "a b", id="1", session_id="sess-1"),
                _sample("c d", "c x", id="2", session_id="sess-2"),
                _sample("e f", "x y", id="3", session_id="sess-3"),
            ]
        )
        macro = _breakdown(aggregation, "session").macro[TIER_A]
        assert macro.word_error_rate.mean == 0.5
        assert macro.word_error_rate.standard_deviation == pytest.approx((1 / 6) ** 0.5)
        assert macro.word_error_rate.median == 0.5

    def test_median_of_an_even_number_of_groups(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "a b", id="1", session_id="sess-1"),
                _sample("c d", "c x", id="2", session_id="sess-2"),
            ]
        )
        macro = _breakdown(aggregation, "session").macro[TIER_A]
        assert macro.word_error_rate.median == 0.25

    def test_a_single_group_has_a_defined_spread_of_zero(self) -> None:
        # The groups of a Breakdown are the whole population, not a sample drawn from one, so the
        # spread of one group is 0.0 rather than a second encoding of "no number here".
        aggregation = aggregate([_sample("a b", "a x")])
        macro = _breakdown(aggregation, "session").macro[TIER_A]
        assert macro.word_error_rate.standard_deviation == 0.0
        assert macro.word_error_rate.excluded_groups == 0


class TestUndefinedness:
    """Decided per Metric, because the three denominators differ (ADR-0018)."""

    def test_all_empty_reference_group_reports_null_wer_and_cer_and_a_real_ser(self) -> None:
        # Tier B empties `Um.`, so `sess-2` holds no Reference tokens and no Reference characters —
        # but it still holds a pair, and empty-against-empty is a correct Sample.
        aggregation = aggregate(
            [
                _sample("hello world", "hello there", id="1", session_id="sess-1"),
                _sample("Um.", "Um.", id="2", session_id="sess-2"),
            ]
        )
        group = _group(aggregation, "session", "sess-2").pooled[TIER_B]
        assert group.words == (0, 0, 0, 0)
        assert group.word_error_rate is None
        assert group.character_error_rate is None
        assert group.sentence_error_rate == 0.0

    def test_exclusion_counts_are_stated_per_metric(self) -> None:
        aggregation = aggregate(
            [
                _sample("hello world", "hello there", id="1", session_id="sess-1"),
                _sample("Um.", "Um.", id="2", session_id="sess-2"),
            ]
        )
        macro = _breakdown(aggregation, "session").macro[TIER_B]
        assert macro.word_error_rate.excluded_groups == 1
        assert macro.character_error_rate.excluded_groups == 1
        assert macro.sentence_error_rate.excluded_groups == 0
        # The mean is over the one surviving group, not over the two the Breakdown emitted.
        assert macro.word_error_rate.mean == 0.5
        assert macro.sentence_error_rate.mean == 0.5

    def test_macro_is_null_when_every_group_is_excluded(self) -> None:
        aggregation = aggregate(
            [
                _sample("Um.", "Um.", id="1", session_id="sess-1"),
                _sample("Uh.", "Uh.", id="2", session_id="sess-2"),
            ]
        )
        macro = _breakdown(aggregation, "session").macro[TIER_B].word_error_rate
        assert (macro.mean, macro.standard_deviation, macro.median) == (None, None, None)
        assert macro.excluded_groups == 2
        # The Scope itself is undefined under Tier B and is emitted as `null` rather than refused:
        # the hard error guards the headline, which is Tier A Pooled WER (ADR-0018, ADR-0022).
        assert aggregation.pooled[TIER_B].word_error_rate is None
        # Tier A cannot empty a non-empty Prompt, so the same Scope is defined under the headline.
        assert _breakdown(aggregation, "session").macro[TIER_A].word_error_rate.mean == 0.0

    def test_a_genuinely_empty_group_is_not_emitted(self) -> None:
        aggregation = aggregate([_sample("a b", "a x", split="test")])
        assert [group.value for group in _breakdown(aggregation, "split").groups] == ["test"]

    def test_ser_is_undefined_only_where_there_are_no_pairs(self) -> None:
        # The state no Breakdown can reach, since an empty group is never emitted — asserted on the
        # object because it is what makes SER's denominator differ from the other two (ADR-0018).
        empty = Pooled(samples=0, words=_EMPTY, characters=_EMPTY, sentence_errors=0)
        assert empty.sentence_error_rate is None

    def test_a_scope_with_zero_reference_tokens_is_a_hard_error(self) -> None:
        # `.` normalizes empty under both tiers: there is no denominator, and a rate without one is
        # not a measurement (ADR-0018).
        with pytest.raises(HardError, match="zero total Reference tokens"):
            aggregate([_sample(".", "hello")])


class TestBreakdowns:
    """Five of them, every group carrying its Sample count, nothing suppressed."""

    def test_all_five_in_a_fixed_order(self) -> None:
        aggregation = aggregate([_sample("a b", "a x")])
        assert [b.attribute for b in aggregation.breakdowns] == [
            "split",
            "session",
            "prompt",
            "device",
            "environment",
        ]

    def test_each_breakdown_groups_by_its_own_attribute(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "a x", id="1", device="mic-a", environment="room-a"),
                _sample("c d", "c d", id="2", device="mic-b", environment="room-a"),
            ]
        )
        assert [g.value for g in _breakdown(aggregation, "device").groups] == ["mic-a", "mic-b"]
        assert [g.value for g in _breakdown(aggregation, "environment").groups] == ["room-a"]

    def test_every_group_carries_its_sample_count(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "a x", id="1", session_id="sess-1"),
                _sample("c d", "c d", id="2", session_id="sess-1"),
                _sample("e f", "x y", id="3", session_id="sess-2"),
            ]
        )
        counts = {g.value: g.samples for g in _breakdown(aggregation, "session").groups}
        assert counts == {"sess-1": 2, "sess-2": 1}

    def test_a_group_of_one_is_emitted_with_its_rate_and_its_size(self) -> None:
        # `1.0 (n=1)` reads as exactly what it is: no threshold suppresses it (ADR-0022).
        aggregation = aggregate(
            [
                _sample("a b", "a b", id="1", prompt_id="p-1"),
                _sample("c d", "x y", id="2", prompt_id="p-2"),
            ]
        )
        hard = _group(aggregation, "prompt", "p-2")
        assert hard.samples == 1
        assert hard.pooled[TIER_A].word_error_rate == 1.0

    def test_the_scope_carries_its_own_sample_count(self) -> None:
        aggregation = aggregate([_sample("a b", "a x", id="1"), _sample("c", "c", id="2")])
        assert aggregation.samples == 2


class TestOrdering:
    """Content-derived and fixed, so two Reports of one corpus line up row for row (ADR-0022)."""

    def test_splits_sort_in_the_build_paths_order(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "a x", id="1", split="test"),
                _sample("c d", "c d", id="2", split="train"),
                _sample("e f", "e f", id="3", split="val"),
            ]
        )
        assert [g.value for g in _breakdown(aggregation, "split").groups] == [
            "train",
            "val",
            "test",
        ]

    def test_an_unknown_split_sorts_last_rather_than_raising(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "a x", id="1", split="holdout"),
                _sample("c d", "c d", id="2", split="train"),
            ]
        )
        assert [g.value for g in _breakdown(aggregation, "split").groups] == ["train", "holdout"]

    def test_other_attributes_sort_by_value_ascending_never_by_rate(self) -> None:
        aggregation = aggregate(
            [
                _sample("a b", "x y", id="1", session_id="sess-b"),
                _sample("c d", "c d", id="2", session_id="sess-a"),
            ]
        )
        groups = _breakdown(aggregation, "session").groups
        assert [g.value for g in groups] == ["sess-a", "sess-b"]
        # Worst-first would have put `sess-b` on top; ordering by rate is what makes two Reports of
        # one corpus reorder under noise.
        assert groups[0].pooled[TIER_A].word_error_rate == 0.0

    def test_tiers_are_emitted_headline_first(self) -> None:
        aggregation = aggregate([_sample("a b", "a x")])
        assert list(aggregation.pooled) == [TIER_A, TIER_B]
        assert list(_breakdown(aggregation, "split").groups[0].pooled) == [TIER_A, TIER_B]
        assert list(_breakdown(aggregation, "split").macro) == [TIER_A, TIER_B]


class TestKeyOrder:
    """Declaration order *is* the emitted key order, so a reordering is caught here (ADR-0018).

    The renderings read these dataclasses field by field, so this is the guard the ADR asks for at
    the layer that fixes the order rather than at the two that reproduce it.
    """

    def test_declared_field_order(self) -> None:
        assert [f.name for f in fields(Aggregation)] == ["samples", "pooled", "breakdowns"]
        assert [f.name for f in fields(Breakdown)] == ["attribute", "groups", "macro"]
        assert [f.name for f in fields(Group)] == ["value", "samples", "pooled"]
        assert [f.name for f in fields(Pooled)] == [
            "samples",
            "words",
            "characters",
            "sentence_errors",
        ]
        assert [f.name for f in fields(Macro)] == [
            "word_error_rate",
            "character_error_rate",
            "sentence_error_rate",
        ]
        assert [f.name for f in fields(MacroStatistic)] == [
            "mean",
            "standard_deviation",
            "median",
            "excluded_groups",
        ]
        assert [f.name for f in fields(ScoredSample)] == [
            "id",
            "split",
            "session_id",
            "prompt_id",
            "device",
            "environment",
            "metrics",
        ]
