"""Soft-flag pass-through: a quality flag annotates a Sample, it never drops or fails it (#33).

ADR-0007's two-outcome model — anything that decodes becomes a Sample carrying zero or more advisory
flags, and the workbench never filters, moves, or deletes a Recording for a flag. This drives that
promise through a whole `build`/`validate`: a `--data-in` that trips `duration_out_of_range` still
yields the flagged Sample in a Manifest *and* in `quality.jsonl`, and `validate` exits 0 despite it.

The Manifest carries no quality fields — flags live only in `reports/quality.jsonl`, joinable on
`id` (ADR-0007). So "present in a Manifest" means the flagged `id` is a Sample line somewhere in
`train`/`val`/`test.jsonl`, not that the flag itself appears there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdw.cli import main
from tests import synth

# A short blip below the 0.5 s floor trips `duration_out_of_range`; the id it takes is stable, so
# the test can name it. Four distinct Sessions (distinct signals, so no two Originals collide) clear
# ADR-0004's >= 3-Session floor and let the split fill all three buckets.
_FLAGGED = "blip.wav"


def _data_in_with_one_flagged_sample(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    synth.write_wav(
        root / _FLAGGED,
        freq_hz=310.0,
        amp_dbfs=-18.0,
        duration_s=0.1,
        sample_rate=16000,
        bit_depth=16,
        channels=1,
    )
    rows = [{"path": _FLAGGED, "session_id": "sess_0", "prompt_text": "A blip."}]
    for index in range(3):
        name = f"clean{index}.wav"
        synth.write_wav(
            root / name,
            freq_hz=350.0 + 40 * index,
            amp_dbfs=-18.0,
            duration_s=1.0 + 0.1 * index,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        rows.append(
            {"path": name, "session_id": f"sess_{index + 1}", "prompt_text": f"Clean {index}."}
        )
    synth.write_recordings_csv(root, rows)
    return root


def _manifest_ids(data_out: Path) -> set[str]:
    ids: set[str] = set()
    for split in ("train", "val", "test"):
        for line in (data_out / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            ids.add(json.loads(line)["id"])
    return ids


def _quality_rows(data_out: Path) -> dict[str, list[str]]:
    rows = {}
    for line in (data_out / "reports" / "quality.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        rows[record["id"]] = record["flags"]
    return rows


class TestSoftFlagPassThrough:
    def test_a_flagged_sample_is_in_a_manifest_and_in_quality_jsonl(self, tmp_path: Path) -> None:
        data_in = _data_in_with_one_flagged_sample(tmp_path / "in")
        data_out = tmp_path / "out"
        assert main(["build", "--data-in", str(data_in), "--data-out", str(data_out)]) == 0

        quality = _quality_rows(data_out)
        flagged = {rec_id for rec_id, flags in quality.items() if "duration_out_of_range" in flags}
        assert len(flagged) == 1

        # The flag annotates rather than excludes: the same id is a Sample in some Manifest, and
        # every Recording — flagged or clean — has exactly one `quality.jsonl` line.
        assert flagged <= _manifest_ids(data_out)
        assert set(quality) == _manifest_ids(data_out)

    def test_validate_exits_zero_despite_the_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A flag is advisory, so a Dataset full of quiet or short Recordings is a report, not a
        # broken CI gate: `validate` is non-zero only on a structural or split failure (ADR-0007).
        data_in = _data_in_with_one_flagged_sample(tmp_path / "in")
        assert main(["validate", "--data-in", str(data_in)]) == 0
        assert "duration_out_of_range" in capsys.readouterr().out
