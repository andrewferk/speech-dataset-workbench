"""Partition the Samples into train/val/test, one whole Session at a time (#27, ADR-0004).

The fourth pipeline stage, and the first one on the `build` side alone. It takes the Recordings
that survived normalize + validate — soft-flagged ones included, because all attempts are data —
and returns a :class:`SplitResult`: which Session went where, plus the facts a later stage needs
to explain that to an operator.

Three facts pin the shape:

- **The unit is the Session and the grouping is not a knob.** A whole Session lands in exactly one
  Split, so a Prompt re-read within a sitting can never straddle train and test. The guarantee is
  session-level, not speaker-level: v0.1 data is single-speaker, and one Speaker cannot fill three
  disjoint splits. A Speaker recurring across splits is therefore expected — surfaced as a
  disclosure when there is more than one Speaker, never as a change to the partition.

- **The targets are absolute Sample counts, computed once.** ``N`` is known before the walk
  begins, so ``target_i = ratio_i x N`` and ``deficit_i = target_i - assigned_i`` are total-order
  stable from the very first Session, with no ``0/0`` special case. Deficits stay floats and go
  **negative** on overshoot — deliberately, so an overshot Split stops attracting Sessions. The
  deficit is never redefined against Samples-assigned-so-far, and never rounded.

- **Nothing here is a decision the tool makes twice.** Order is ``sha256("<seed>:<session_id>")``,
  destination ties break by :data:`SPLIT_ORDER`, and the repair recomputes state between moves.
  No RNG, no clock, no host facts — the same ``--data-in`` plus the same effective config yields a
  byte-identical split. Cross-*version* stability is not claimed: adding a Recording may reshuffle
  the partition, which is fine because a changed input is already a new ``dataset_version``.

**The disclosures are returned as data, not rendered.** The repair moves, the speaker-overlap
finding, the targets beside the realized counts, and the below-minimum flag are all fields on the
result; `summary.txt` (#10) owns the prose. That keeps this module a pure function and keeps the
one place that phrases a split fact from being three.

The result carries what a caller reads and no more (#70) — see :class:`SplitResult` for the rule
and for the quantities that are a caller's own subtraction rather than a field.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from sdw.config import SplitConfig
from sdw.ingest import Recording

# The three splits, in the order that breaks every tie: destination ties during the walk, donor
# ties during the repair, and the order the repair itself visits starved splits. Total, stable,
# and seed-independent — hashing the split *name* instead would make tie-breaks seed-dependent
# and the ADR's worked example unverifiable by hand (ADR-0004).
SPLIT_ORDER = ("train", "val", "test")

# Non-emptiness is only achievable — and so only promised — once there is one Session per split.
MIN_SESSIONS_FOR_REPAIR = 3

# A donor must keep a Session after donating, or the repair merely relocates the emptiness it was
# called to fix. Load-bearing, not decoration: in ADR-0004's worked example the largest-surplus
# split holds exactly one Session and is ineligible for precisely this reason.
MIN_DONOR_SESSIONS = 2


@dataclass(frozen=True)
class RepairMove:
    """One non-emptiness repair: a Session taken from ``donor`` and given to ``recipient``.

    Reported because the realized counts show the repair's *outcome* but not its *mechanism* — an
    operator seeing ``test = 3`` cannot otherwise tell whether water-filling chose it or the
    repair rescued it, and those mean different things about their data (ADR-0004).
    """

    session_id: str
    donor: str
    recipient: str


@dataclass(frozen=True)
class SpeakerOverlap:
    """One Speaker appearing in more than one Split — report-only, and never blocking.

    Emitted only when the Dataset has more than one distinct Speaker: on single-speaker data,
    which is v0.1's expected shape, the overlap is unavoidable and the note would fire on every
    build while naming nothing the operator could act on (ADR-0004).
    """

    speaker_id: str
    splits: tuple[str, ...]


@dataclass(frozen=True)
class SplitResult:
    """The partition plus everything needed to explain it, all as data.

    ``targets`` beside ``samples`` is the ratio disclosure's whole substance: an operator who
    configures 80-10-10 and receives 50-25-25 is looking at arithmetic — whole Sessions are
    indivisible — and both numbers being present lets them draw that conclusion themselves.

    **A field earns its place here if a production caller reads it, or if it is read and its
    derivation encodes a decision this module owns** (#70). *Production* is load-bearing: a test is
    a caller too, and all three fields removed by #70 had a test reading them. Being read by the
    suite is what makes a field look alive, not what earns it.

    Per-Split Session counts, per-Split deficits, and the set of empty Splits were all once fields
    and are none of them now: each is arithmetic over a field still published here — a count over
    ``assignments``, ``targets`` less ``samples``, a ``samples`` count of zero — and the arithmetic
    carries no decision, so a caller that wants one can do it. ``below_min_sessions`` stays under
    the second clause: the :data:`MIN_SESSIONS_FOR_REPAIR` comparison is this module's rule about
    when it makes the non-emptiness promise, and #10 re-deriving it would put that judgement in the
    renderer.

    There is deliberately no companion flag for an empty Split at or above
    :data:`MIN_SESSIONS_FOR_REPAIR` Sessions — the "repair failed to buy a promise the tool made"
    case. ADR-0004's pigeonhole argument proves an eligible donor always exists there, so the
    warning would be prose no build can emit. Were the proof ever to stop holding, the failure is
    already legible in `summary.txt`: a realized count of zero beside a nonzero target, with no
    repair line beneath it.
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
    Never raises and never aborts — an input too small for three splits produces a valid partition
    with empty ``val``/``test`` and flags it, because refusing to build would block the operator
    during exactly the bootstrapping phase the tool has to be usable in.
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

    A hex sort key rather than a seeded shuffle: ``random.shuffle`` can drift across Python
    versions, which would break the byte-identical claim ``dataset_version`` rests on. Hashing
    also decorrelates the walk from any ordering baked into the id, so "test" is not simply the
    newest Sessions.
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
    ordering is not incidental to this line.
    """
    return max(SPLIT_ORDER, key=lambda name: targets[name] - assigned[name])


def _repair(
    assignments: dict[str, str],
    order: tuple[str, ...],
    sizes: dict[str, int],
    targets: dict[str, float],
) -> tuple[RepairMove, ...]:
    """Give a starved ``val``/``test`` one Session each, at the least ratio cost available.

    Mutates ``assignments`` in place and returns what it did. Runs only with at least three
    Sessions — below that a three-way split is mathematically impossible and there is nothing to
    repair. State is recomputed between the two moves, so repairing ``val`` can change which split
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

    Largest-surplus rather than "always train": ratios are operator-configurable, so under
    ``train = 0.2`` a fixed train donor could strip train to empty while repairing test, inverting
    the guarantee the repair exists to serve. Pigeonhole makes an eligible donor certain whenever
    there are >= 3 Sessions and a Split is empty, so ``None`` is unreachable in practice — returned
    rather than asserted so a future ratio rule cannot turn a disclosure into a crash.
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

    The repair is a deliberate ratio violation in service of non-emptiness, so it should cost the
    least ratio fidelity available — moving a 9-Sample Session where a 1-Sample one was there
    damages both splits to satisfy a guarantee one Sample would meet (ADR-0004).

    ``held`` is built in hash order and :func:`min` keeps the first of equal keys, so the size tie
    falls to hash order without a second sort key.
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
