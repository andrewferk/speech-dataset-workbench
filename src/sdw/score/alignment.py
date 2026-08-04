"""Levenshtein with backtrace, costs 0/1/1/1, pure Python and no dependencies (ADR-0018).

Ours rather than a library's because every edge case that matters is one we override anyway, and
because "byte-identical on any machine" is a contract that an integer DP makes trivially true.
"""

from collections.abc import Sequence
from typing import NamedTuple


class Alignment(NamedTuple):
    """One aligned pair's error counts, with the Reference length the rate divides by.

    The counts are the source of truth and are emitted exactly; :attr:`rate` is derived (ADR-0018).
    """

    substitutions: int
    deletions: int
    insertions: int
    reference_length: int

    @property
    def errors(self) -> int:
        """S + D + I — the numerator of every rate this module feeds."""
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float | None:
        """Errors over Reference length, or `None` where the Reference is empty.

        Never clamped and never a sentinel: a rate above 1.0 is the real value, and an undefined
        one is an absence rather than a `0.0` or an `inf` that would survive aggregation as a lie.
        """
        if self.reference_length == 0:
            return None
        return self.errors / self.reference_length


def align(reference: Sequence[str], hypothesis: Sequence[str]) -> Alignment:
    """Align two sequences of comparable items — tokens for WER, characters for CER.

    Reference runs along `i` and Hypothesis along `j`, so a step in `i` alone is a deletion and a
    step in `j` alone an insertion.
    """
    n, m = len(reference), len(hypothesis)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(
                cost[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]),
                cost[i - 1][j] + 1,
                cost[i][j - 1] + 1,
            )

    substitutions = deletions = insertions = 0
    i, j = n, m
    while i or j:
        # The branch order *is* the tie-break — diagonal, then deletion, then insertion, among the
        # steps achieving this cell's minimum. Reordering them leaves every total untouched and
        # changes the reported S/D/I split, which is an output change (ADR-0018).
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (reference[i - 1] != hypothesis[j - 1]):
            substitutions += reference[i - 1] != hypothesis[j - 1]
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return Alignment(substitutions, deletions, insertions, n)
