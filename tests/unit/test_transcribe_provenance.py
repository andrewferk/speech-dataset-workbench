"""The Run's name, its timestamps, and the language block (#164, ADR-0020/ADR-0021).

`run.json`'s shape is asserted field-wise from a real Run in `tests/e2e/test_transcribe.py`; what is
here is the part that has no observed values in it — the two timestamp spellings, and the language
resolution that turns v0.1's `null` into a disclosed default.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sdw.transcribe import provenance
from sdw.transcribe.backend import BackendProvenance, Language, resolve_language
from sdw.transcribe.dataset import Descriptor
from sdw.transcribe.provenance import Timing

MOMENT = datetime(2026, 8, 3, 14, 22, 5, tzinfo=UTC)

BACKEND = BackendProvenance(
    model={"repo_id": "fake/model"}, decode={"task": "transcribe"}, runtime={"name": "fake"}
)

DESCRIPTOR = Descriptor(
    dataset_version="sha256:" + "a" * 64,
    tool_version="0.1.0",
    manifest_version="0.1",
    lang=None,
)


def test_the_run_directory_name_is_basic_format_utc() -> None:
    # Not hash-shaped, which would smuggle *equal implies identical content* through the filesystem;
    # not sequential, which would require reading sibling directories (ADR-0021).
    assert provenance.run_directory_name(MOMENT) == "run-20260803T142205Z"


def test_the_file_records_the_extended_spelling() -> None:
    assert provenance.timestamp(MOMENT) == "2026-08-03T14:22:05Z"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [(None, Language("en", "defaulted")), ("de", Language("de", "declared"))],
)
def test_language_records_its_source(declared: str | None, expected: Language) -> None:
    # Defaulting keeps an unlabelled v0.1 dataset evaluable; recording the source is what stops the
    # convenience becoming a silent assumption (ADR-0016).
    assert resolve_language(declared) == expected


def test_both_timestamps_are_recorded_and_no_duration_is() -> None:
    # Duration is derivable, and a number recorded twice is a number that can disagree with itself.
    document = json.loads(
        provenance.render(
            descriptor=DESCRIPTOR,
            backend=BACKEND,
            language=resolve_language(DESCRIPTOR.lang),
            record_line_count=53,
            timing=Timing(started_at="2026-08-03T14:02:11Z", finished_at="2026-08-03T14:07:48Z"),
        )
    )
    assert document["timing"] == {
        "started_at": "2026-08-03T14:02:11Z",
        "finished_at": "2026-08-03T14:07:48Z",
    }
    assert "duration" not in json.dumps(document)
    assert document["record_line_count"] == 53
