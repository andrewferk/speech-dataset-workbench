"""The Levenshtein scorer and its tie-break, which is a contract rather than an incident (ADR-0018).

Every expected count here is computed by hand. The total cost is what a library would agree on; the
S/D/I *split* is what ADR-0018 fixes and what these tests exist to pin, because two conforming
implementations report different splits for the same input without a stated rule.

An :class:`Alignment` compares equal to its own fields in order, so the tuples below read
``(substitutions, deletions, insertions, reference_length)``.
"""

import pytest

from sdw.score.alignment import align


class TestCosts:
    """0/1/1/1 — correct, insertion, deletion, substitution."""

    def test_identical_sequences_cost_nothing(self) -> None:
        assert align(["a", "b", "c"], ["a", "b", "c"]) == (0, 0, 0, 3)

    def test_one_wrong_token_is_one_substitution(self) -> None:
        assert align(["a", "b", "c"], ["a", "x", "c"]) == (1, 0, 0, 3)

    def test_a_missing_token_is_one_deletion(self) -> None:
        assert align(["a", "b", "c"], ["a", "c"]) == (0, 1, 0, 3)

    def test_an_extra_token_is_one_insertion(self) -> None:
        assert align(["a", "c"], ["a", "b", "c"]) == (0, 0, 1, 2)

    def test_reference_runs_along_i_and_hypothesis_along_j(self) -> None:
        # The orientation is the whole of what makes D and I distinguishable (ADR-0018): a step in
        # `i` alone is a deletion. Swapping the arguments must swap exactly those two counts.
        forward = align(["a", "b", "c"], ["a"])
        backward = align(["a"], ["a", "b", "c"])
        assert (forward.deletions, forward.insertions) == (2, 0)
        assert (backward.deletions, backward.insertions) == (0, 2)


class TestTieBreak:
    """Diagonal, then deletion, then insertion — among the steps achieving a cell's minimum."""

    def test_diagonal_beats_a_deletion_and_insertion_pair(self) -> None:
        # ADR-0018's own example. `a b` against `b a` costs 2 either way: two substitutions, or one
        # deletion plus one insertion. Diagonal-first reports the substitutions — the reading of an
        # aligned pair a human expects.
        #
        # This is the one value in the suite where both oracles disagree with us, and the
        # disagreement is ours by decision rather than by error: `jiwer` walks to the deletion and
        # insertion, and `sclite` genuinely prefers them because its 0/3/3/4 weights price two
        # substitutions at 8 against the pair's 6. ADR-0018 chose 0/3/3/4's *opposite* and said
        # why — the weights move only this tie-break, and the S/D/I split is reported, so it is
        # visible rather than buried. The totals agree everywhere, including here.
        assert align(["a", "b"], ["b", "a"]) == (2, 0, 0, 2)

    def test_deletion_beats_insertion_where_the_diagonal_is_not_minimal(self) -> None:
        # `a b a` against `b c a b` costs 3 two ways, and here the split genuinely differs:
        # insert `b`, insert `c`, match `a`, match `b`, delete the trailing `a` — S=0, D=1, I=2 —
        # against substitute `a`→`b`, substitute `b`→`c`, match `a`, insert `b` — S=2, D=0, I=1.
        # At the final cell the diagonal is not minimal while deletion and insertion both are, so
        # this is the fixture that pins the second rule; preferring insertion would report (2,0,1).
        assert align(["a", "b", "a"], ["b", "c", "a", "b"]) == (0, 1, 2, 3)

    def test_the_total_is_unaffected_by_which_minimal_path_is_walked(self) -> None:
        # The tie-break moves the split, never the sum — which is why WER, CER and SER are safe
        # under either rule and why only the emitted counts need it written down.
        for alignment in (align(["a", "b"], ["b", "a"]), align(["a", "b", "a"], ["b", "c", "a"])):
            assert alignment.errors == 2


class TestDegenerateInputs:
    """ADR-0018's table, at the alignment layer: every one has a value and none is an exception."""

    def test_an_empty_reference_against_a_hypothesis_is_all_insertions(self) -> None:
        assert align([], ["a", "b", "c"]) == (0, 0, 3, 0)

    def test_an_empty_reference_against_an_empty_hypothesis_is_no_errors(self) -> None:
        assert align([], []) == (0, 0, 0, 0)

    def test_an_empty_hypothesis_is_a_deletion_per_reference_token(self) -> None:
        assert align(["a", "b", "c"], []) == (0, 3, 0, 3)

    def test_an_undefined_rate_is_none_and_never_a_sentinel_number(self) -> None:
        # `0.0` claims perfection and `inf` claims catastrophe; a `null` propagates as an absence
        # (ADR-0018). The insertions are still counted exactly — Pooling is what consumes them.
        alignment = align([], ["a", "b", "c"])
        assert alignment.rate is None
        assert alignment.errors == 3

    def test_an_empty_hypothesis_rates_at_exactly_one(self) -> None:
        assert align(["a", "b", "c"], []).rate == 1.0

    def test_a_rate_above_one_is_reported_as_computed(self) -> None:
        # Unclamped, ratifying ADR-0015: a runaway decode has to be visible as a number above 1.0
        # rather than tidied away at the boundary.
        assert align(["a"], ["x", "y", "z", "w"]).rate == 4.0


class TestSequenceKinds:
    """One function over any sequence of comparable items — words and characters both."""

    def test_characters_align_as_readily_as_tokens(self) -> None:
        # CER is the same arithmetic over characters, so a `str` is a valid argument as it stands.
        assert align("kitten", "sitting") == (2, 0, 1, 6)

    def test_the_space_is_an_ordinary_character(self) -> None:
        # CER counts it (ADR-0018), which is what keeps CER sensitive to word-boundary errors.
        assert align("a b", "ab") == (0, 1, 0, 3)


class TestExactness:
    """Integer counts are the source of truth; the rate is derived from them."""

    def test_the_counts_are_ints_and_the_rate_is_their_quotient(self) -> None:
        alignment = align(["a", "b", "c", "d"], ["a", "x", "c"])
        assert (alignment.substitutions, alignment.deletions, alignment.insertions) == (1, 1, 0)
        assert alignment.errors == 2
        assert alignment.rate == 0.5

    def test_it_is_frozen(self) -> None:
        # Counts get pooled and re-aggregated downstream; a mutable alignment is a rate that can
        # disagree with the counts it was derived from.
        with pytest.raises(AttributeError):
            align("a", "a").substitutions = 1  # type: ignore[misc]
