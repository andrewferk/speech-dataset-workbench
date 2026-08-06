"""The digest's fixed shape, and how it spells a fact it quotes.

The shape is invariant (ADR-0022): every row prints at every value, so a diff between two Reports
shows a value changing rather than a line appearing. That has to hold for a `run.json` missing a
block too — the header is not allowed to shrink around a Run whose provenance is thin, because a
shrinking header is exactly the diff that reads as "nothing changed."
"""

from __future__ import annotations

import re
from typing import Any

from sdw.score import digest
from sdw.score.report import Report

_ROWS = ("model", "decode", "language", "dataset_version", "runtime", "host", "tool")


def _report(provenance: dict[str, Any]) -> Report:
    return Report(
        splits=("train",),
        selected_split=None,
        in_scope=1,
        scored=1,
        failed=0,
        long_form=0,
        provenance=provenance,
        tool_version="0.2.0",
    )


def _rows(rendered: str) -> dict[str, str]:
    """The provenance rows as ``label -> value``; the header's rows are not indented."""
    matches = (re.match(r"^ {2}(\S+) +(.*)$", line) for line in rendered.splitlines())
    return {match[1]: match[2] for match in matches if match}


def test_every_provenance_row_prints_even_when_the_file_carries_none_of_them() -> None:
    rows = _rows(digest.render(_report({"record_line_count": 1})))

    assert list(rows) == list(_ROWS)
    assert [rows[row] for row in _ROWS[:-1]] == [digest.ABSENT] * (len(_ROWS) - 1)
    assert rows["tool"] == f"transcribed {digest.ABSENT}"


def test_a_partially_present_block_prints_the_facts_it_has() -> None:
    rendered = digest.render(_report({"model": {"repo_id": "openai/whisper-tiny"}}))

    assert f"openai/whisper-tiny @ {digest.ABSENT} ({digest.ABSENT})" in rendered


def test_json_scalars_are_spelled_as_the_file_spells_them() -> None:
    # `null` and `false`, never `None` and `False`: the digest quotes `run.json`, and a reader
    # comparing a Report against the file should not have to translate.
    rendered = digest.render(
        _report({"decode": {"temperature": None, "do_sample": False, "num_beams": 1}})
    )

    assert "task" not in rendered
    assert "temperature=null · do_sample=false · num_beams=1" in rendered


def test_the_headers_five_items_print_for_a_run_with_no_provenance_at_all() -> None:
    rendered = digest.render(_report({}))

    assert "Scope        train (every Split present)" in rendered
    assert "1 of 1 scored — 0 Transcription failure(s), 0 long_form" in rendered
    assert "scored by sdw 0.2.0" in rendered
