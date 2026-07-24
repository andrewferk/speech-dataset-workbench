"""Partition the Samples into train/val/test, one whole Session at a time (#27, ADR-0004).

The fourth pipeline stage. It takes the Recordings that survived normalize + validate (soft-flagged
included — all attempts are data) and returns a :class:`SplitResult`: the assignment plus the facts
a later stage needs to explain it. Disclosures are data, not prose — `summary.txt` (#10) renders
them.

Determinism is byte-exact and load-bearing (ADR-0004): order is ``sha256("<seed>:<session_id>")``,
ties break by :data:`SPLIT_ORDER`, deficits are absolute Sample counts — never rounded, never
redefined against Samples-assigned-so-far — that go negative on overshoot, and the repair recomputes
state between moves. No RNG, clock, or host facts.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from sdw.config import SplitConfig
from sdw.ingest import Recording

# The order that breaks every tie: destination during the walk, donor during the repair, and the
# order the repair visits starved splits. Total, stable, seed-independent — hashing the split *name*
# would make tie-breaks seed-dependent and the ADR's worked example unverifiable by hand (ADR-0004).
SPLIT_ORDER = ("train", "val", "test")

# Non-emptiness is only achievable — and so only promised — once there is one Session per split.
MIN_SESSIONS_FOR_REPAIR = 3

# A donor must keep a Session after donating, or the repair merely relocates the emptiness it was
# called to fix (ADR-0004).
MIN_DONOR_SESSIONS = 2


@dataclass(frozen=True)
class RepairMove:
    """One non-emptiness repair: a Session taken from ``donor`` and given to ``recipient``.

    Reported because the realized counts show the repair's *outcome* but not its *mechanism* —
    ``test = 3`` alone cannot say whether water-filling chose it or the repair rescued it, and those
    mean different things about the data (ADR-0004).
    """

    session_id: str
    donor: str
    recipient: str


@dataclass(frozen=True)
class SpeakerOverlap:
    """One Speaker appearing in more than one Split — report-only, never blocking.

    Emitted only with more than one distinct Speaker: on single-speaker data (v0.1's expected shape)
    the overlap is unavoidable and the note would fire on every build naming nothing actionable
    (ADR-0004).
    """

    speaker_id: str
    splits: tuple[str, ...]


@dataclass(frozen=True)
class SplitResult:
    """The partition plus everything needed to explain it, all as data.

    ``targets`` beside ``samples`` is the ratio disclosure — both shown so a caller reads a missed
    ratio as arithmetic, not a bug (ADR-0004).

    Fields are minimal (#70): one is present only if a *production* caller reads it, or its
    derivation encodes a decision this module owns. Session counts, deficits, and the empty-Split
    set are omitted as arithmetic over published fields; ``below_min_sessions`` stays because the
    :data:`MIN_SESSIONS_FOR_REPAIR` comparison is this module's rule, not #10's — and there is no
    empty-Split flag above that count, since pigeonhole guarantees a donor (ADR-0004).
    """

    assignments: dict[str, str]
    order: tuple[str, ...]
    total_samples: int
    targets: dict[str, float]
    samples: dict[str, int]
    moves: tuple[RepairMove, ...]
    speaker_overlaps: tuple[SpeakerOverlap, ...]
    below_min_sessions: bool

    def split_of(self, recording: Recording) -> str:
        """The Split this Recording's Sample belongs to — its Session's, by definition."""
        return self.assignments[recording.session_id]


def split_sessions(recordings: Sequence[Recording], config: SplitConfig) -> SplitResult:
    """Assign every Session to exactly one Split, deterministically (ADR-0004).

    Pure: the same Recordings (in any order) and the same config always produce the same result.
    Never raises and never aborts — an input too small for three splits yields a valid partition
    with empty ``val``/``test``, flagged, so the operator isn't blocked while bootstrapping.
    """
    sizes = _session_sizes(recordings)
    order = _hash_order(sizes, config.seed)
    total = sum(sizes.values())
    targets = {name: getattr(config, name) * total for name in SPLIT_ORDER}

    assignments = _water_fill(order, sizes, targets)
    moves = _repair(assignments, order, sizes, targets)

    return SplitResult(
        assignments=assignments,
        order=order,
        total_samples=total,
        targets=targets,
        samples=_samples_per_split(assignments, sizes),
        moves=moves,
        speaker_overlaps=_speaker_overlaps(recordings, assignments),
        below_min_sessions=len(order) < MIN_SESSIONS_FOR_REPAIR,
    )


def _session_sizes(recordings: Sequence[Recording]) -> dict[str, int]:
    """Sample count per Session. Kept Recordings map 1:1 to Samples in v0.1."""
    sizes: dict[str, int] = {}
    for recording in recordings:
        sizes[recording.session_id] = sizes.get(recording.session_id, 0) + 1
    return sizes


def _hash_order(sizes: dict[str, int], seed: int) -> tuple[str, ...]:
    """Sessions ordered by ``sha256("<seed>:<session_id>")``.

    A stable hex sort key: ``random.shuffle`` would look equivalent but drifts across Python
    versions, breaking the byte-identity ``dataset_version`` rests on (ADR-0004).
    """
    return tuple(
        sorted(sizes, key=lambda sid: hashlib.sha256(f"{seed}:{sid}".encode()).hexdigest())
    )


def _water_fill(
    order: tuple[str, ...], sizes: dict[str, int], targets: dict[str, float]
) -> dict[str, str]:
    """Walk the Sessions in hash order, each to the Split with the maximum deficit."""
    assignments: dict[str, str] = {}
    assigned = dict.fromkeys(SPLIT_ORDER, 0)
    for session_id in order:
        destination = _max_deficit(targets, assigned)
        assignments[session_id] = destination
        assigned[destination] += sizes[session_id]
    return assignments


def _max_deficit(targets: dict[str, float], assigned: dict[str, int]) -> str:
    """The hungriest Split; ties fall to :data:`SPLIT_ORDER`, leftmost winning.

    ``max`` over ``SPLIT_ORDER`` keeps the first maximum it sees, which *is* the tie-break — the
    ordering is not incidental here.
    """
    return max(SPLIT_ORDER, key=lambda name: targets[name] - assigned[name])


def _repair(
    assignments: dict[str, str],
    order: tuple[str, ...],
    sizes: dict[str, int],
    targets: dict[str, float],
) -> tuple[RepairMove, ...]:
    """Give a starved ``val``/``test`` one Session each, at the least ratio cost (ADR-0004).

    Mutates ``assignments`` in place and returns what it did. Runs only with at least three
    Sessions. State is recomputed between the two moves, so repairing ``val`` can change which split
    donates to ``test``.
    """
    if len(order) < MIN_SESSIONS_FOR_REPAIR:
        return ()

    moves: list[RepairMove] = []
    for starved in SPLIT_ORDER[1:]:
        if _sessions_per_split(assignments)[starved]:
            continue
        donor = _donor_split(assignments, sizes, targets)
        if donor is not None:
            session_id = _smallest_session(assignments, order, sizes, donor)
            assignments[session_id] = starved
            moves.append(RepairMove(session_id=session_id, donor=donor, recipient=starved))
    return tuple(moves)


def _donor_split(
    assignments: dict[str, str], sizes: dict[str, int], targets: dict[str, float]
) -> str | None:
    """The minimum-deficit Split — the largest surplus — that can spare a Session.

    Largest-surplus, not "always train": under ``train = 0.2`` a fixed train donor could strip train
    to empty while repairing test, inverting the guarantee (ADR-0004). Pigeonhole makes a donor
    certain at >= 3 Sessions, so ``None`` is unreachable — returned rather than asserted so a future
    ratio rule cannot turn a disclosure into a crash.
    """
    samples = _samples_per_split(assignments, sizes)
    sessions = _sessions_per_split(assignments)
    eligible = [name for name in SPLIT_ORDER if sessions[name] >= MIN_DONOR_SESSIONS]
    if not eligible:
        return None
    return min(eligible, key=lambda name: targets[name] - samples[name])


def _smallest_session(
    assignments: dict[str, str], order: tuple[str, ...], sizes: dict[str, int], donor: str
) -> str:
    """The donor's Session with the fewest Samples; size ties fall to hash order, first winning.

    Least ratio cost: moving a 9-Sample Session where a 1-Sample one was there damages both splits
    to satisfy a guarantee one Sample would meet (ADR-0004). ``held`` is built in hash order and
    :func:`min` keeps the first of equal keys, so the size tie needs no second sort key.
    """
    held = [session_id for session_id in order if assignments[session_id] == donor]
    return min(held, key=lambda session_id: sizes[session_id])


def _samples_per_split(assignments: dict[str, str], sizes: dict[str, int]) -> dict[str, int]:
    """Samples per Split — what the ratios target, and so what a deficit is measured in."""
    counts = dict.fromkeys(SPLIT_ORDER, 0)
    for session_id, name in assignments.items():
        counts[name] += sizes[session_id]
    return counts


def _sessions_per_split(assignments: dict[str, str]) -> dict[str, int]:
    """Sessions per Split — what the donor filter and the starvation check read."""
    counts = dict.fromkeys(SPLIT_ORDER, 0)
    for name in assignments.values():
        counts[name] += 1
    return counts


def _speaker_overlaps(
    recordings: Sequence[Recording], assignments: dict[str, str]
) -> tuple[SpeakerOverlap, ...]:
    """Speakers landing in more than one Split — suppressed entirely for single-speaker data."""
    per_speaker: dict[str, set[str]] = {}
    for recording in recordings:
        per_speaker.setdefault(recording.speaker_id, set()).add(assignments[recording.session_id])
    if len(per_speaker) < 2:
        return ()
    return tuple(
        SpeakerOverlap(
            speaker_id=speaker_id,
            splits=tuple(name for name in SPLIT_ORDER if name in splits),
        )
        for speaker_id, splits in sorted(per_speaker.items())
        if len(splits) > 1
    )
