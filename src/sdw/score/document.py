"""The JSON rendering: the same Report as the digest, at the machine's resolution (ADR-0022).

One JSON document, not JSONL — a Report is one object, where `quality.jsonl` and the Manifest are
line-per-entity files a consumer streams and joins. Key order is fixed by declaration order.

The `run` key carries `run.json` **verbatim** — not a projection, not a re-nesting, not a curated
subset — so ADR-0020's tier table applies to the Report without translation and a diff scoped to
that key *is* the tier check (ADR-0024). The digest may reorganise because it is read; this may not,
because it is diffed.
"""

from __future__ import annotations

from sdw.score.report import COMPARABILITY_NOTE, REFERENCE_NOTE, Report, normalizers
from sdw.serialization import render_json


def render(report: Report) -> str:
    """The whole document as one string, LF-terminated."""
    tier_a, tier_b = normalizers()
    return render_json(
        {
            "scope": {"split": report.selected_split, "splits_present": list(report.splits)},
            # ADR-0017's N-of-M, as the counts the digest renders as a sentence.
            "samples": {
                "in_scope": report.in_scope,
                "scored": report.scored,
                "failed": report.failed,
                "long_form": report.long_form,
            },
            # The same fixed sentences the digest prints: two renderings of one Report, so the
            # disclosures are shared rather than re-worded per rendering (ADR-0022).
            "disclosures": {"reference": REFERENCE_NOTE, "comparability": COMPARABILITY_NOTE},
            "normalizers": {"tier_a": tier_a, "tier_b": tier_b},
            "tool_version": report.tool_version,
            # As read, key order included — the echo is quotation, not a second record.
            "run": report.provenance,
        }
    )
