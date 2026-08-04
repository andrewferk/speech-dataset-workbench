"""`run.json`: the Run's provenance, and the completeness sentinel (ADR-0020).

Deliberately parallel to `dataset.json` — a descriptor beside the data it describes, written
**last** — but carrying provenance in place of an identifier: **a Run has no id**, because an
id-shaped string in this file would be read as the *equal implies identical content* contract a
non-deterministic Run cannot honour. Its handle is its directory name (ADR-0021).

This module shares a name with `sdw.provenance` and imports nothing from it: the stranger-consumer
rule holds at any depth (ADR-0017), and the two files answer to different regimes — wall-clock and
host facts belong here and are forbidden on a Record line. The boundary is the file, not a
compromise (ADR-0020).
"""

import json
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sdw import __version__
from sdw.serialization import JSON_ENSURE_ASCII, JSON_SEPARATORS
from sdw.transcribe.backend import BackendProvenance, Language
from sdw.transcribe.dataset import Descriptor
from sdw.transcribe.record import RECORD_VERSION

RUN_DESCRIPTOR_NAME = "run.json"

# `run-` + basic-format ISO 8601, UTC, second resolution, Z-suffixed (ADR-0021). Not hash-shaped,
# which would smuggle a false guarantee through the filesystem, and not sequential, which would
# require reading sibling directories.
RUN_DIR_PREFIX = "run-"
_DIR_TIMESTAMP = "%Y%m%dT%H%M%SZ"

# The extended form the file records. The name is a default *label* and may be renamed freely;
# `run.json` is the authoritative record of when the Run started (ADR-0021).
_FILE_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Timing:
    """When the Run started and finished — both, never a duration, which is derivable (ADR-0020)."""

    started_at: str
    finished_at: str


def run_directory_name(started: datetime) -> str:
    """The default label for a Run directory, minted from the clock at creation (ADR-0021)."""
    return RUN_DIR_PREFIX + started.strftime(_DIR_TIMESTAMP)


def timestamp(moment: datetime) -> str:
    """One wall-clock fact as `run.json` spells it."""
    return moment.strftime(_FILE_TIMESTAMP)


def render(
    *,
    descriptor: Descriptor,
    backend: BackendProvenance,
    language: Language,
    record_line_count: int,
    timing: Timing,
) -> str:
    """`run.json`'s bytes: nested blocks, canonical JSON, in ADR-0020's order.

    Nesting is chosen for the comparability rule rather than for tidiness — drawn along the lines
    the rule cares about, the blocks make it *"these must match; those two are a caveat; that one
    never matters"*, applicable by eye where twenty flat keys are a checklist.

    Top-level `tool_version` names the tool that wrote *this* file, which is the rule that holds in
    all three artifacts; `dataset.tool_version` is the tool that built the dataset, and neither is
    assumed equal to the other or to the one that will score it (ADR-0020). The Normalizer identity
    strings are absent on purpose: Text Normalization happens in `score`, and this file would be
    describing an event that had not happened when it was written.
    """
    return _render(
        {
            "record_version": RECORD_VERSION,
            "record_line_count": record_line_count,
            "tool_version": __version__,
            "dataset": {
                "dataset_version": descriptor.dataset_version,
                "tool_version": descriptor.tool_version,
                # Which Manifest schema this Run read — real provenance for a stranger parser, and
                # the field that would explain a future parse divergence (ADR-0020).
                "manifest_version": descriptor.manifest_version,
            },
            "model": dict(backend.model),
            "decode": dict(backend.decode),
            "language": {"value": language.value, "source": language.source},
            "runtime": dict(backend.runtime),
            "host": _host(),
            "timing": {"started_at": timing.started_at, "finished_at": timing.finished_at},
        }
    )


def _host() -> dict[str, str]:
    """The host facts, on the numerics argument rather than the diary one (ADR-0020).

    Architecture is the other input to the reduction-order fact `torch_num_threads` is recorded for.
    No hostname, no username, no absolute paths: no attribution value on a single-operator tool, and
    the one part of the excluded set that is identity-shaped rather than merely non-deterministic.
    """
    return {"platform_machine": platform.machine(), "platform_system": platform.system()}


def _render(document: Mapping[str, Any]) -> str:
    """The descriptor as text: compact, LF-terminated, keys in insertion order.

    Same byte format as every other artifact `sdw` writes (ADR-0006/ADR-0019) — `sort_keys` off, so
    the nested blocks stay in the order the comparability rule reads them in.
    """
    return json.dumps(document, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
