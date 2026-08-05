"""Pooled at every level, Macro across a Breakdown's groups, and the five Breakdowns (ADR-0018).

Aggregation runs over Samples that were **scored**, so a failed Sample never reaches here: it has no
Hypothesis to align and is disclosed as a count instead (ADR-0018). Rates stay unrounded — rounding
belongs to serialization (ADR-0007) — and every rate is derived from integer counts that are
themselves emitted, so a later re-aggregation needs no re-scoring.
"""

import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from sdw.errors import HardError
from sdw.score.alignment import Alignment
from sdw.score.metrics import SampleMetrics, score_sample
from sdw.score.text_normalization import NORMALIZERS, TIER_A

# Both tiers, headline first — one order every level of the Report shares (ADR-0018).
TIERS = tuple(NORMALIZERS)

# Reimplemented, never imported: the eval path is a stranger consumer of the build path's output,
# and importing `sdw.split.SPLIT_ORDER` would breach that boundary for a four-element tuple
# (ADR-0017, ADR-0022). A Split outside it still sorts — see :func:`_split_key`.
SPLIT_ORDER = ("train", "val", "test")


@dataclass(frozen=True)
class ScoredSample:
    """One Sample's Metrics under both tiers, beside the attributes the Breakdowns group by."""

    id: str
    split: str
    session_id: str
    prompt_id: str
    device: str
    environment: str
    metrics: Mapping[str, SampleMetrics]


@dataclass(frozen=True)
class Pooled:
    """Errors summed and denominators summed, divided once — the rate at any level (ADR-0018).

    `samples` is this tier's SER denominator, which is why it sits beside the two alignments rather
    than only on the group above.
    """

    samples: int
    words: Alignment
    characters: Alignment
    sentence_errors: int

    @property
    def word_error_rate(self) -> float | None:
        """`None` where every Reference in the pool normalized empty — undefined, not zero."""
        return self.words.rate

    @property
    def character_error_rate(self) -> float | None:
        """`None` where every Reference in the pool normalized empty — undefined, not zero."""
        return self.characters.rate

    @property
    def sentence_error_rate(self) -> float | None:
        """`None` only where the pool holds no pairs; an all-empty-Reference pool has a real one."""
        if self.samples == 0:
            return None
        return self.sentence_errors / self.samples


@dataclass(frozen=True)
class MacroStatistic:
    """One Metric's spread across a Breakdown's groups, with the groups it could not use.

    `excluded_groups` counts the groups whose Pooled rate is undefined *for this Metric*; with every
    group excluded the three statistics are `None` rather than `0.0` (ADR-0018).
    """

    mean: float | None
    standard_deviation: float | None
    median: float | None
    excluded_groups: int


@dataclass(frozen=True)
class Macro:
    """The three Metrics' Macro statistics for one Breakdown under one tier."""

    word_error_rate: MacroStatistic
    character_error_rate: MacroStatistic
    sentence_error_rate: MacroStatistic


@dataclass(frozen=True)
class Group:
    """One Breakdown group: its attribute value, its size, and its Pooled numbers per tier.

    `samples` is the `n` printed beside every rate, so a group of one reads as a group of one
    (ADR-0022). Nothing is suppressed and no threshold exists.
    """

    value: str
    samples: int
    pooled: Mapping[str, Pooled]


@dataclass(frozen=True)
class Breakdown:
    """One axis: its groups in fixed content-derived order, and the Macro across them per tier."""

    attribute: str
    groups: tuple[Group, ...]
    macro: Mapping[str, Macro]


@dataclass(frozen=True)
class Aggregation:
    """Every number a Report states about a Scope, above the per-Sample rows."""

    samples: int
    pooled: Mapping[str, Pooled]
    breakdowns: tuple[Breakdown, ...]


# The five axes, in the order the Report prints them: the Breakdown's domain name, then the
# :class:`ScoredSample` field it groups by (ADR-0022).
_AXES: tuple[tuple[str, str], ...] = (
    ("split", "split"),
    ("session", "session_id"),
    ("prompt", "prompt_id"),
    ("device", "device"),
    ("environment", "environment"),
)


def scored(
    *,
    id: str,
    reference: str,
    hypothesis: str,
    split: str,
    session_id: str,
    prompt_id: str,
    device: str,
    environment: str,
) -> ScoredSample:
    """Score one Sample under both tiers and carry its Breakdown attributes alongside."""
    return ScoredSample(
        id=id,
        split=split,
        session_id=session_id,
        prompt_id=prompt_id,
        device=device,
        environment=environment,
        metrics=score_sample(reference, hypothesis),
    )


def aggregate(samples: Sequence[ScoredSample]) -> Aggregation:
    """Pool the Scope, then build all five Breakdowns over it.

    Raises :class:`~sdw.errors.HardError` when the Scope holds zero Reference tokens under the
    headline tier: `0.0` claims perfection and `inf` claims catastrophe, and neither is a
    measurement (ADR-0018). A *group* in that state is emitted with `null` instead — one degenerate
    group must not suppress an otherwise valid Report.
    """
    pooled = _pool(samples)
    if pooled[TIER_A].words.reference_length == 0:
        raise HardError(
            f"the Scope has zero total Reference tokens under {TIER_A}: "
            "a rate with no denominator is not a measurement"
        )
    return Aggregation(
        samples=len(samples),
        pooled=pooled,
        breakdowns=tuple(_breakdown(samples, name, field) for name, field in _AXES),
    )


def _breakdown(samples: Sequence[ScoredSample], name: str, field: str) -> Breakdown:
    """Group by one attribute, ordered by attribute value — never by rate (ADR-0022).

    Only values the Scope actually holds become groups, so a genuinely empty group is never emitted.
    """
    members: dict[str, list[ScoredSample]] = {}
    for sample in samples:
        members.setdefault(getattr(sample, field), []).append(sample)
    ordered = sorted(members, key=_split_key) if field == "split" else sorted(members)
    groups = tuple(_group(value, members[value]) for value in ordered)
    return Breakdown(
        attribute=name,
        groups=groups,
        macro=_by_tier(lambda tier: _macro(groups, tier)),
    )


def _group(value: str, members: Sequence[ScoredSample]) -> Group:
    return Group(value=value, samples=len(members), pooled=_pool(members))


def _pool(samples: Sequence[ScoredSample]) -> Mapping[str, Pooled]:
    return _by_tier(
        lambda tier: Pooled(
            samples=len(samples),
            words=_sum([sample.metrics[tier].words for sample in samples]),
            characters=_sum([sample.metrics[tier].characters for sample in samples]),
            sentence_errors=sum(sample.metrics[tier].sentence_error for sample in samples),
        )
    )


def _sum(alignments: Iterable[Alignment]) -> Alignment:
    """Counts summed componentwise; :attr:`Alignment.rate` then divides once, as Pooling needs."""
    total = Alignment(0, 0, 0, 0)
    for alignment in alignments:
        total = Alignment(*(a + b for a, b in zip(total, alignment, strict=True)))
    return total


def _macro(groups: Sequence[Group], tier: str) -> Macro:
    """Mean, SD and median over each group's *Pooled* rate, never over per-Sample rates."""
    return Macro(
        word_error_rate=_statistic(groups, tier, lambda pooled: pooled.word_error_rate),
        character_error_rate=_statistic(groups, tier, lambda pooled: pooled.character_error_rate),
        sentence_error_rate=_statistic(groups, tier, lambda pooled: pooled.sentence_error_rate),
    )


def _statistic(
    groups: Sequence[Group], tier: str, rate: Callable[[Pooled], float | None]
) -> MacroStatistic:
    rates = [rate(group.pooled[tier]) for group in groups]
    defined = [value for value in rates if value is not None]
    if not defined:
        return MacroStatistic(None, None, None, len(rates))
    return MacroStatistic(
        mean=statistics.fmean(defined),
        # Population, not sample: a Breakdown's groups *are* the population, so a one-group spread
        # is 0.0 rather than a second encoding of "no number here" beside ADR-0018's `null`.
        standard_deviation=statistics.pstdev(defined),
        median=statistics.median(defined),
        excluded_groups=len(rates) - len(defined),
    )


def _by_tier[T](build: Callable[[str], T]) -> Mapping[str, T]:
    return MappingProxyType({tier: build(tier) for tier in TIERS})


def _split_key(value: str) -> tuple[int, str]:
    """ADR-0004's order, with any Split the build path never emits sorting after it by value."""
    return (
        SPLIT_ORDER.index(value) if value in SPLIT_ORDER else len(SPLIT_ORDER),
        value,
    )
