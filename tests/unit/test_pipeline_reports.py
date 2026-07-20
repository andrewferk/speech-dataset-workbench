"""Where the reporting stage sits in the two commands (#32, ADR-0007/0004).

`reports/` is written by `build` and only by `build`: `validate` prints the same quality digest to
stdout and writes nothing, anywhere (ADR-0002). And because a build lands as one atomic commit, an
abort leaves no `reports/` at all — a half-written `quality.jsonl` would be indistinguishable from
a Dataset that genuinely had fewer Recordings, which is exactly the confusion the file exists to
prevent.

These tests assert placement and atomicity. What the two files *say* is `test_reports.py`.
"""

import json
from pathlib import Path

import pytest

from sdw.cli import main
from sdw.errors import HardError
from sdw.reports import QUALITY_JSONL, REPORTS_DIR, SUMMARY_TXT
from tests import synth


def _data_in(root: Path, count: int) -> Path:
    """A `--data-in` of ``count`` distinct Recordings, one Session each so a repair is available."""
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        name = f"r{index}.wav"
        synth.write_wav(
            root / name,
            freq_hz=300.0 + 50 * index,
            amp_dbfs=-18.0,
            duration_s=0.5 + 0.1 * index,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        rows.append({"path": name, "session_id": f"sess_{index}", "prompt_text": f"Line {index}."})
    synth.write_recordings_csv(root, rows)
    return root


class TestBuildWritesReports:
    """Both artifacts land in the committed tree, one `quality.jsonl` line per Recording."""

    def test_both_files_are_committed(self, tmp_path: Path) -> None:
        data_out = tmp_path / "out"
        assert (
            main(
                [
                    "build",
                    "--data-in",
                    str(_data_in(tmp_path / "in", 4)),
                    "--data-out",
                    str(data_out),
                ]
            )
            == 0
        )

        reports = data_out / REPORTS_DIR
        assert (reports / SUMMARY_TXT).is_file()
        lines = [json.loads(text) for text in (reports / QUALITY_JSONL).read_text().splitlines()]
        assert len(lines) == 4
        assert [line["id"] for line in lines] == sorted(line["id"] for line in lines)

    def test_summary_carries_the_split_table_on_a_clean_build(self, tmp_path: Path) -> None:
        """No threshold and no conditional — the disclosure is unconditional (ADR-0004)."""
        data_out = tmp_path / "out"
        main(["build", "--data-in", str(_data_in(tmp_path / "in", 4)), "--data-out", str(data_out)])
        summary = (data_out / REPORTS_DIR / SUMMARY_TXT).read_text(encoding="utf-8")
        assert "Quality:" in summary
        assert "realized" in summary


class TestValidateWritesNothing:
    """`validate` prints the digest and leaves no durable artifact (ADR-0002)."""

    def test_no_reports_directory_is_created(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data_in = _data_in(tmp_path / "in", 3)
        assert main(["validate", "--data-in", str(data_in)]) == 0
        assert capsys.readouterr().out.startswith("Quality:")
        assert not (data_in / REPORTS_DIR).exists()
        assert not (tmp_path / REPORTS_DIR).exists()


class TestAbortLeavesNoReports:
    """An abort anywhere leaves no durable `--data-out`, reports included (ADR-0003)."""

    def test_render_failure_removes_the_staged_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sdw import images

        def _boom(*args: object, **kwargs: object) -> None:
            raise HardError("render failed")

        monkeypatch.setattr(images, "render", _boom)
        data_out = tmp_path / "out"
        assert (
            main(
                [
                    "build",
                    "--data-in",
                    str(_data_in(tmp_path / "in", 3)),
                    "--data-out",
                    str(data_out),
                ]
            )
            == 1
        )
        assert not data_out.exists()
        assert not data_out.with_name("out.tmp").exists()
