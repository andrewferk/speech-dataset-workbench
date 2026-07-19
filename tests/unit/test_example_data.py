"""The committed example ``--data-in`` (ADR-0009).

The drift guard first: the committed tree still matches what ``examples/generate.py`` produces, so
divergence between the generator and its output is a CI failure rather than a maintenance chore.
This is safe to assert byte-exactly because the generator writes 16 kHz mono directly and never
resamples — ADR-0005's within-arch-only caveat is about soxr, which is not in this loop.

The rest pin the *shape* ADR-0009 chose to teach with — 2 Speakers, 4 Sessions, 12 Samples, one
Prompt recorded twice within a Session, exactly one Recording under the `low_volume` knob — because
that shape is the example's whole content, and a well-meaning edit could quietly erase any of it.

Nothing here invokes ``build``: the example depends only on the generator.
"""

import csv
from pathlib import Path

import numpy as np
import soundfile as sf

from examples import generate
from sdw.config import QualityConfig
from sdw.ingest import COLUMNS, read_recordings
from sdw.normalize import TARGET_SAMPLE_RATE
from sdw.quality import CLIP_THRESHOLD

COMMITTED = generate.DATA_IN

# ADR-0009: ~12 clips of a few seconds at mono/16 kHz/16-bit is well under a megabyte, and the
# tree is committed with no gitignore entries — so a ceiling is worth stating as a test.
MAX_TREE_BYTES = 1_000_000


def _relative_wavs(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*.wav")}


def test_committed_tree_matches_the_generator(tmp_path: Path) -> None:
    regenerated = tmp_path / "data-in"
    generate.write_example_tree(regenerated)

    assert _relative_wavs(COMMITTED) == _relative_wavs(regenerated)

    for name in sorted(_relative_wavs(COMMITTED) | {"recordings.csv"}):
        assert (COMMITTED / name).read_bytes() == (regenerated / name).read_bytes(), name


def test_tree_is_small_enough_to_commit() -> None:
    total = sum(p.stat().st_size for p in COMMITTED.rglob("*") if p.is_file())
    assert total < MAX_TREE_BYTES, total


def test_no_gitignore_entries_under_the_example_tree() -> None:
    # ADR-0002/ADR-0009: raw audio is kept out of git architecturally, not by a rule someone can
    # forget, so the example tree carries no ignore file of its own.
    assert not list(COMMITTED.rglob(".gitignore"))


def test_shape_is_two_speakers_four_sessions_twelve_samples() -> None:
    recordings = read_recordings(COMMITTED)
    assert len(recordings) == 12
    assert len({r.speaker_id for r in recordings}) == 2
    assert len({r.session_id for r in recordings}) == 4
    # Every Session belongs to exactly one Speaker — Session-level disjointness (ADR-0004) is only
    # meaningful if a Session does not straddle Speakers.
    by_session: dict[str, set[str]] = {}
    for r in recordings:
        by_session.setdefault(r.session_id, set()).add(r.speaker_id)
    assert all(len(speakers) == 1 for speakers in by_session.values())


def test_one_prompt_is_recorded_twice_within_one_session() -> None:
    # `(Session, Prompt)` is not unique and all attempts are data (ADR-0001). Both takes survive
    # ingest as separate Recordings, which they only do if their bytes differ.
    recordings = read_recordings(COMMITTED)
    counts: dict[tuple[str, str], int] = {}
    for r in recordings:
        key = (r.session_id, r.prompt_id)
        counts[key] = counts.get(key, 0) + 1
    repeated = [key for key, n in counts.items() if n > 1]
    assert len(repeated) == 1
    assert counts[repeated[0]] == 2


def test_every_recording_is_byte_distinct() -> None:
    # A Recording's bytes follow entirely from its `(freq_hz, duration_s, amp_dbfs)` triple, so two
    # Recordings sharing a triple would be byte-identical Originals and collapse to one Recording
    # at ingest (ADR-0001) — a corpus quietly one Sample shorter than it reads. Asserted on the
    # generator's table, where the mistake is made, as well as on the committed bytes.
    triples = {(r.freq_hz, r.duration_s, r.amp_dbfs) for r in generate.RECORDINGS}
    assert len(triples) == len(generate.RECORDINGS)

    contents = {(COMMITTED / r.path).read_bytes() for r in generate.RECORDINGS}
    assert len(contents) == len(generate.RECORDINGS)


def test_exactly_one_recording_is_below_the_low_volume_threshold() -> None:
    # Measured the way the pipeline measures it, on the audio as committed: one flagged Recording
    # is the point (ADR-0007/ADR-0009), and it stays in the corpus.
    threshold = QualityConfig().low_volume_rms_dbfs
    quiet = [path for path in sorted(COMMITTED.rglob("*.wav")) if _rms_dbfs(path) < threshold]
    assert len(quiet) == 1


def test_every_recording_clears_the_other_flags() -> None:
    # Only the deliberate `low_volume` should fire: a demo whose first run flags three things
    # reads as a broken corpus rather than a worked example.
    config = QualityConfig()
    for path in sorted(COMMITTED.rglob("*.wav")):
        samples, rate = sf.read(path, dtype="float64", always_2d=False)
        duration_s = len(samples) / rate
        assert config.duration_min_s <= duration_s <= config.duration_max_s, path
        assert float(np.abs(samples).max()) < CLIP_THRESHOLD, path


def test_audio_is_written_at_the_normalized_target() -> None:
    # 16 kHz mono, so the generator never resamples and the byte comparison above is safely exact.
    for path in sorted(COMMITTED.rglob("*.wav")):
        info = sf.info(path)
        assert (info.samplerate, info.channels, info.subtype) == (
            TARGET_SAMPLE_RATE,
            1,
            "PCM_16",
        ), path


def test_recordings_csv_is_the_operators_template() -> None:
    # The demo CSV *is* the bring-your-own template (ADR-0009), so it must carry exactly the
    # documented column set, in order, with POSIX-relative paths that resolve. Checked against
    # `sdw.ingest.COLUMNS` — the product's own idea of the contract — rather than against the
    # generator's copy, which would only prove the generator agrees with itself.
    with (COMMITTED / "recordings.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 12
    assert list(rows[0].keys()) == list(COLUMNS)
    for row in rows:
        assert not row["path"].startswith("/")
        assert ".." not in Path(row["path"]).parts
        assert (COMMITTED / row["path"]).is_file(), row["path"]
        # Honest English Prompts against generated tones (ADR-0009): a sentence, not a tone label.
        assert row["prompt_text"].endswith((".", "?", "!")), row["prompt_text"]


def _rms_dbfs(path: Path) -> float:
    samples, _ = sf.read(path, dtype="float64", always_2d=False)
    return float(20.0 * np.log10(np.sqrt(np.mean(np.square(samples)))))
