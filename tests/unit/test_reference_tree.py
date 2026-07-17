"""The committed reference ``--data-in`` (ADR-0008).

Two things are pinned here: the committed tree still matches what the generator produces
(a drift guard, mirroring ADR-0009's example-data test), and it covers the four normalization
paths the golden end-to-end test will exercise (ADR-0005). The tree is resample-free, so the
byte comparison is safe to assert exactly (ADR-0008/ADR-0009).
"""

import csv
from pathlib import Path

import soundfile as sf

from tests import synth

REPO_ROOT = Path(__file__).parents[2]
REFERENCE = REPO_ROOT / "tests" / "fixtures" / "reference"


def _wavs(root: Path) -> list[Path]:
    return sorted(root.glob("*.wav"))


def test_committed_tree_matches_the_generator(tmp_path: Path) -> None:
    # Regenerate into a tmpdir and byte-compare: drift between generator and committed output
    # is a CI failure, not a maintenance chore.
    regenerated = tmp_path / "reference"
    synth.write_reference_tree(regenerated)

    committed = {p.name for p in _wavs(REFERENCE)} | {"recordings.csv"}
    fresh = {p.name for p in _wavs(regenerated)} | {"recordings.csv"}
    assert committed == fresh

    for name in sorted(committed):
        assert (REFERENCE / name).read_bytes() == (regenerated / name).read_bytes(), name


def test_covers_the_four_normalization_paths() -> None:
    infos = [sf.info(p) for p in _wavs(REFERENCE)]
    specs = {(info.samplerate, info.channels, info.subtype) for info in infos}
    assert (16000, 1, "PCM_16") in specs  # already-16k-mono passthrough
    assert any(info.samplerate == 48000 for info in infos)  # 48k -> 16k resample
    assert any(info.channels == 2 for info in infos)  # stereo -> mono downmix
    assert any(info.subtype == "PCM_24" for info in infos)  # 24 -> 16 bit


def test_recordings_csv_is_well_formed() -> None:
    with (REFERENCE / "recordings.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows, "reference recordings.csv must not be empty"
    assert list(rows[0].keys()) == [
        "path",
        "speaker_id",
        "session_id",
        "prompt_text",
        "device",
        "environment",
    ]
    for row in rows:
        rel = row["path"]
        # POSIX-relative, within --data-in (ADR-0003): no absolute paths, no ..-escapes.
        assert not rel.startswith("/")
        assert ".." not in Path(rel).parts
        assert (REFERENCE / rel).is_file(), rel
