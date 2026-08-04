"""`run.json`: the Run's provenance, and the completeness sentinel (ADR-0020).

Written last, and carrying no Run identifier and no hash over the Record: an id-shaped string here
would assert a guarantee a non-deterministic Run cannot make (ADR-0020). Wall-clock and host facts
belong in this file and nowhere else — the boundary is the file, so a Record line stays free of
them (ADR-0019/ADR-0020).

It shares a name with `sdw.provenance` and imports nothing from it (ADR-0017).
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
    """`run.json`'s bytes: canonical JSON, nested blocks, in ADR-0020's order.

    The blocks are the comparability rule's tiers, so flattening or reordering them breaks a rule
    stated over their names. Top-level `tool_version` names the tool that wrote *this* file;
    `dataset.tool_version` names the one that built the dataset, and neither is assumed equal to
    the other or to the scoring occurrence (ADR-0020).
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
    """Architecture and OS — the two host facts a future comparison needs (ADR-0020).

    No hostname, no username, no absolute paths: those are the identity-shaped part of the excluded
    set, and adding one would put a fact about the operator into a durable artifact.
    """
    return {"platform_machine": platform.machine(), "platform_system": platform.system()}


def _render(document: Mapping[str, Any]) -> str:
    """The descriptor as text: compact, LF-terminated, keys in insertion order.

    Same byte format as every other artifact `sdw` writes (ADR-0006/ADR-0019) — `sort_keys` off, so
    the nested blocks stay in the order the comparability rule reads them in.
    """
    return json.dumps(document, ensure_ascii=JSON_ENSURE_ASCII, separators=JSON_SEPARATORS) + "\n"
