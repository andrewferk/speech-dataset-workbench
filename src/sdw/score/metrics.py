"""The per-Sample scorer: WER, CER and SER, under both tiers, from one normalized pair (ADR-0018).

Word-level and character-level counts are emitted separately because CER is its own alignment — per
Sample, never concatenated — so its errors are not derivable from the word-level ones. Rates are
derived from those counts and are rounded at serialization, never here.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from sdw.score.alignment import Alignment, align
from sdw.score.text_normalization import NORMALIZERS


@dataclass(frozen=True)
class SampleScore:
    """One Sample's three Metrics under one Normalizer, with the text they were computed from.

    Field order is a Report's key order (ADR-0018), so reordering these is an output change.
    """

    reference: str
    hypothesis: str
    words: Alignment
    characters: Alignment
    sentence_error: bool

    @property
    def word_error_rate(self) -> float | None:
        """`None` where the normalized Reference holds no tokens — undefined, not zero."""
        return self.words.rate

    @property
    def character_error_rate(self) -> float | None:
        """`None` where the normalized Reference holds no characters — undefined, not zero."""
        return self.characters.rate

    @property
    def sentence_error_rate(self) -> float:
        """Always defined: SER's denominator is pairs, and one Sample is one pair (ADR-0018)."""
        return float(self.sentence_error)


def score_sample(reference: str, hypothesis: str) -> Mapping[str, SampleScore]:
    """Score one Reference/Hypothesis pair under every Normalizer, keyed by identity string.

    Both tiers always run, over the identical Sample: a Sample dropped under one tier — an empty
    normalized Reference is the case that arises — would end the paired B−A delta (ADR-0018).
    Takes the Hypothesis a Record holds; a *failed* Sample has none and is never passed here.
    """
    return {
        identity: _score(normalizer(reference), normalizer(hypothesis))
        for identity, normalizer in NORMALIZERS.items()
    }


def _score(reference: str, hypothesis: str) -> SampleScore:
    """All three Metrics off the same normalized pair, so they cannot disagree about the text."""
    return SampleScore(
        reference=reference,
        hypothesis=hypothesis,
        # `split()` over `split(" ")`, which reads `""` as one empty token. The Normalizer already
        # guarantees single-space separation; this is not a repair of ragged whitespace.
        words=align(reference.split(), hypothesis.split()),
        # A `str` is a sequence of its characters, and the space is one of them (ADR-0018).
        characters=align(reference, hypothesis),
        sentence_error=reference != hypothesis,
    )
