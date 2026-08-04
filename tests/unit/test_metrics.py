"""WER, CER and SER for one Sample, under both tiers, from the same normalized text (ADR-0018).

Every expected value below is computed by hand from the normalized strings the assertions name, so
a failure says which of the two layers moved.

The values were validated once against `sclite` (SCTK, word level) and `jiwer` (word and character
level) as dev-only oracles and then frozen, per ADR-0025. Neither is a test dependency, appears in
`pyproject.toml`, or is installed by any CI job. Both agreed on every count here; the sole
disagreement in the suite is the backtrace tie-break, which is ours by decision and is argued at
`tests/unit/test_alignment.py::TestTieBreak`. Two rows have no `sclite` representation and were
checked against `jiwer` alone — an empty normalized Reference, and an empty against an empty.
"""

import inspect

import pytest

from sdw.score.metrics import SampleMetrics, score_sample
from sdw.score.text_normalization import TIER_A, TIER_B, tier_a, tier_b


def _tier_a(reference: str, hypothesis: str) -> SampleMetrics:
    return score_sample(reference, hypothesis)[TIER_A]


def _tier_b(reference: str, hypothesis: str) -> SampleMetrics:
    return score_sample(reference, hypothesis)[TIER_B]


class TestWordErrorRate:
    """(S + D + I) / N over whitespace-separated tokens, N the Reference token count."""

    def test_one_wrong_word_in_four(self) -> None:
        # `the quick brown fox` against `the quick brown box`: one substitution over four tokens.
        metrics = _tier_a("The quick brown fox.", "The quick brown box!")
        assert metrics.words == (1, 0, 0, 4)
        assert metrics.word_error_rate == 0.25

    def test_tokens_are_whitespace_separated(self) -> None:
        # The Normalizer guarantees single-space separation, so `hello world` is two tokens and not
        # the one a literal-space tokenizer reads out of a surviving tab (ADR-0018's 200% trap).
        metrics = _tier_a("hello\tworld", "hello world")
        assert metrics.words == (0, 0, 0, 2)
        assert metrics.word_error_rate == 0.0


class TestCharacterErrorRate:
    """The same arithmetic over characters, aligned per Sample — never concatenated."""

    def test_one_wrong_character_in_nineteen(self) -> None:
        # `the quick brown fox` and `the quick brown box` are both 19 characters and differ in one.
        metrics = _tier_a("The quick brown fox.", "The quick brown box!")
        assert metrics.characters == (1, 0, 0, 19)
        assert metrics.character_error_rate == 1 / 19

    def test_the_space_counts_as_a_character(self) -> None:
        # Excluding it would make CER blind to word-boundary errors — a real class on a prompted
        # corpus (ADR-0018). `co worker` against `coworker` is one deletion over nine characters.
        metrics = _tier_a("co-worker", "coworker")
        assert metrics.characters == (0, 1, 0, 9)
        assert metrics.character_error_rate == 1 / 9

    def test_it_is_its_own_alignment_and_not_derivable_from_the_word_counts(self) -> None:
        # One substituted word is one word error and however many character errors the words
        # actually differ by, which is why both sets of counts are emitted (ADR-0018).
        # `the cat` against `the elephant`: one substituted word, and at character level the `a`
        # and the `t` survive as matches, so `c`→`e` is a substitution and five characters insert.
        metrics = _tier_a("the cat", "the elephant")
        assert metrics.words == (1, 0, 0, 2)
        assert metrics.characters == (1, 0, 5, 7)


class TestSentenceErrorRate:
    """An exact-match binary over the normalized strings."""

    def test_identical_normalized_text_is_correct(self) -> None:
        # Text Normalization is what makes this an equivalence rather than a string compare: the
        # punctuation and case differ and the Sample is still correct.
        metrics = _tier_a("Hello, world!", "hello world")
        assert metrics.sentence_error is False

    def test_any_difference_at_all_is_an_error(self) -> None:
        metrics = _tier_a("hello world", "hello word")
        assert metrics.sentence_error is True


class TestDegenerateInputs:
    """ADR-0018's table, row by row. Every one has a value and none of them is an exception."""

    def test_empty_reference_against_a_non_empty_hypothesis(self) -> None:
        # Tier B empties `Um.` where Tier A gives `um`, so this row is reached through Tier B.
        # `hello` is one insertion against no tokens and five against no characters; the rates are
        # undefined, and the counts are exactly what Pooling adds to a zero denominator.
        assert (tier_b("Um."), tier_b("Um hello.")) == ("", "hello")
        metrics = _tier_b("Um.", "Um hello.")
        assert metrics.words == (0, 0, 1, 0)
        assert metrics.characters == (0, 0, 5, 0)
        assert metrics.word_error_rate is None
        assert metrics.character_error_rate is None
        assert metrics.sentence_error is True

    def test_empty_reference_against_an_empty_hypothesis_scores_ser_correct(self) -> None:
        # The row that decides SER's denominator is pairs rather than tokens: nothing was said and
        # nothing was heard, so the Sample is *correct* while WER and CER stay undefined.
        assert (tier_b("Um."), tier_b("Uh.")) == ("", "")
        metrics = _tier_b("Um.", "Uh.")
        assert metrics.words == (0, 0, 0, 0)
        assert metrics.characters == (0, 0, 0, 0)
        assert metrics.word_error_rate is None
        assert metrics.character_error_rate is None
        assert metrics.sentence_error is False

    def test_a_non_empty_reference_against_an_empty_hypothesis_rates_at_one(self) -> None:
        # An empty Hypothesis is the model's output and is scored; a *failed* Sample is the absence
        # of output and gets no row at all. The two must not land on the same number (ADR-0018).
        metrics = _tier_a("Hello world.", "")
        assert metrics.words == (0, 2, 0, 2)
        assert metrics.characters == (0, 11, 0, 11)
        assert metrics.word_error_rate == 1.0
        assert metrics.character_error_rate == 1.0

    def test_a_rate_above_one_is_reported_as_computed(self) -> None:
        # `go` against `go on then now please`: four inserted tokens over one, and nineteen
        # inserted characters over two. There is no clamp anywhere — a runaway decode is meant to
        # be visible as a number above 1.0 (ADR-0015, ADR-0016).
        metrics = _tier_a("Go.", "Go on then now please.")
        assert metrics.words == (0, 0, 4, 1)
        assert metrics.characters == (0, 0, 19, 2)
        assert metrics.word_error_rate == 4.0
        assert metrics.character_error_rate == 9.5

    def test_no_undefined_rate_is_a_sentinel_number(self) -> None:
        # `jiwer` returning a raw insertion count from a function documented to return a rate is
        # the failure this guards: a `null` propagates as an absence, a `0.0` or an `inf` as a lie.
        metrics = _tier_b("Um.", "Um hello.")
        for rate in (metrics.word_error_rate, metrics.character_error_rate):
            assert rate is None

    def test_a_failed_sample_cannot_be_scored_at_all(self) -> None:
        # The one row of the table whose value is not a number. A crashed decode wrote no
        # Hypothesis, so there is no pair to align and the Sample gets no row — #159 owns reading
        # that marker and #161 the N-of-M disclosure. What this layer owes the rule is the absence
        # of a path: scoring takes a `str`, so a missing Hypothesis cannot arrive disguised as an
        # empty one, which would score N deletions and make a crash indistinguishable from silence.
        assert [p.annotation for p in inspect.signature(score_sample).parameters.values()] == [
            str,
            str,
        ]


class TestBothTiers:
    """Both Normalizers always run, over the identical Sample, from the same normalized text."""

    def test_every_sample_is_scored_under_exactly_the_two_tiers(self) -> None:
        assert set(score_sample("Um.", "Um hello.")) == {TIER_A, TIER_B}

    def test_an_empty_reference_is_retained_rather_than_dropped(self) -> None:
        # Dropping it would make the two tiers score different Sample sets and destroy the paired
        # exactness that is the entire reason for computing two tiers (ADR-0018).
        scores = score_sample("Um.", "Um.")
        assert set(scores) == {TIER_A, TIER_B}
        assert scores[TIER_B].reference == ""
        assert scores[TIER_B].words.reference_length == 0

    def test_the_tiers_disagree_on_the_same_input_which_is_the_delta_being_measured(self) -> None:
        # `um hello` against `hello` under Tier A is one deletion over two tokens; Tier B removes
        # the filler from both sides and scores the pair as correct. The B−A delta is a number
        # (#161's to pool), and it exists because both tiers ran over one Sample.
        scores = score_sample("Um hello.", "Hello.")
        assert scores[TIER_A].word_error_rate == 0.5
        assert scores[TIER_B].word_error_rate == 0.0

    def test_each_tier_scores_the_text_its_own_normalizer_produced(self) -> None:
        reference = "It's Dr. Smith's well-known co-worker."
        hypothesis = "its dr smith is well known"
        scores = score_sample(reference, hypothesis)
        assert (scores[TIER_A].reference, scores[TIER_A].hypothesis) == (
            tier_a(reference),
            tier_a(hypothesis),
        )
        assert (scores[TIER_B].reference, scores[TIER_B].hypothesis) == (
            tier_b(reference),
            tier_b(hypothesis),
        )

    def test_all_three_metrics_come_from_that_one_normalized_pair(self) -> None:
        # Not three normalizations: WER, CER and SER must not be able to disagree about what the
        # text was, or the SER binary could report correct while WER reports errors.
        metrics = _tier_a("Hello, world!", "hello world")
        assert metrics.words == (0, 0, 0, 2)
        assert metrics.characters == (0, 0, 0, 11)
        assert metrics.sentence_error is False


class TestExactness:
    """Integer counts are the source of truth; rates are derived, and nothing rounds here."""

    def test_rates_are_not_rounded_at_measurement(self) -> None:
        # Rounding is serialization's business at `RATIO_DP` (ADR-0007, ADR-0018); a rate rounded
        # here would be a measurement that cannot be recomputed from the counts beside it.
        metrics = _tier_a("The quick brown fox.", "The quick brown box!")
        assert metrics.character_error_rate == 1 / 19

    def test_every_rate_is_recomputable_from_the_emitted_counts(self) -> None:
        metrics = _tier_a("the cat sat", "a cat sat down")
        assert metrics.word_error_rate == metrics.words.errors / metrics.words.reference_length
        assert (
            metrics.character_error_rate
            == metrics.characters.errors / metrics.characters.reference_length
        )

    def test_a_samples_metrics_are_frozen(self) -> None:
        with pytest.raises(AttributeError):
            _tier_a("a", "a").sentence_error = True  # type: ignore[misc]
