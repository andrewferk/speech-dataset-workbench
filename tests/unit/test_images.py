"""The two PNGs per Recording, their fixed scales, and their determinism (#31, ADR-0011).

An Image states measurements, never verdicts. These tests pin the three properties that claim
buys, each of which is a property of *what the file says*, not of how it was drawn:

- **The numbers are the quality stage's, verbatim.** The title is rendered from metrics the caller
  passes in, so a metrics record that deliberately disagrees with the plotted audio still shows up
  in the title unchanged. That is the recomputation ban, asserted rather than trusted: a stage that
  recomputed peak/RMS from the samples could not pass it.
- **The scales are absolute.** Two recordings differing only in level must produce two *different*
  pictures. Autoscale — waveform y or per-image dB normalization — makes them identical, which is
  precisely the lie ADR-0011 fixed the axes to prevent.
- **The bytes are stable on one machine.** Rendering twice byte-matches, and no `Software` chunk
  names a matplotlib version. Cross-machine byte-identity is explicitly out of scope (ADR-0011).
"""

from pathlib import Path
from typing import Any

import pytest

from sdw.errors import HardError
from sdw.images import (
    DB_RANGE,
    SPECTROGRAM_SIZE_PX,
    WAVEFORM_SIZE_PX,
    WAVEFORM_YLIM,
    image_paths,
    render,
    title,
)
from sdw.ingest import Recording
from sdw.normalize import NormalizedAudio, normalize
from sdw.quality import QualityMetrics
from tests import synth

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

RECORDING = Recording(
    recording_id="rec_0123456789abcdef",
    content_hash="0" * 64,
    prompt_id="1" * 64,
    path="a.wav",
    speaker_id="spk_a",
    session_id="sess_1",
    prompt_text="Hello there.",
    device="mic",
    environment="quiet room",
)

METRICS = QualityMetrics(
    duration_s=0.5,
    peak_dbfs=-3.01,
    clip_ratio=0.0,
    active_rms_dbfs=-18.0,
    leading_silence_s=0.0,
    trailing_silence_s=0.0,
    silence_ratio=0.0,
    flags=(),
)


def _audio(path: Path, *, amp_dbfs: float = -18.0, duration_s: float = 0.5) -> NormalizedAudio:
    synth.write_wav(
        path,
        freq_hz=400.0,
        amp_dbfs=amp_dbfs,
        duration_s=duration_s,
        sample_rate=16000,
        bit_depth=16,
        channels=1,
    )
    return normalize(path)


def _render(tmp_path: Path, **kwargs: Any) -> Path:
    """Render the default Recording into a fresh `images/` and return that directory."""
    out_dir = tmp_path / "images"
    audio = kwargs.pop("audio", None) or _audio(tmp_path / "a.wav")
    render(audio, kwargs.pop("metrics", METRICS), RECORDING, out_dir)
    return out_dir


def _png_size(path: Path) -> tuple[int, int]:
    """`(width, height)` read straight from the PNG IHDR — no image library needed."""
    header = path.read_bytes()[16:24]
    return int.from_bytes(header[:4], "big"), int.from_bytes(header[4:], "big")


class TestCoverage:
    """Exactly two PNGs per Recording, named from the `recording_id` stem (ADR-0003)."""

    def test_writes_exactly_two_pngs(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        assert sorted(p.name for p in out_dir.iterdir()) == [
            "rec_0123456789abcdef.spectrogram.png",
            "rec_0123456789abcdef.waveform.png",
        ]

    def test_both_files_are_pngs(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        for path in out_dir.iterdir():
            assert path.read_bytes().startswith(PNG_MAGIC)

    def test_image_paths_names_what_render_writes(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        assert {p.name for p in image_paths(RECORDING.recording_id, out_dir)} == {
            p.name for p in out_dir.iterdir()
        }

    def test_creates_the_output_directory(self, tmp_path: Path) -> None:
        audio = _audio(tmp_path / "a.wav")
        nested = tmp_path / "out" / "images"
        render(audio, METRICS, RECORDING, nested)
        assert len(list(nested.iterdir())) == 2


class TestFixedGeometry:
    """Figure size and DPI are pinned constants, so every Image is the same pixel size."""

    def test_waveform_pixel_size(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        assert _png_size(out_dir / "rec_0123456789abcdef.waveform.png") == WAVEFORM_SIZE_PX

    def test_spectrogram_pixel_size(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        assert _png_size(out_dir / "rec_0123456789abcdef.spectrogram.png") == SPECTROGRAM_SIZE_PX

    def test_pixel_size_is_independent_of_duration(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path, audio=_audio(tmp_path / "long.wav", duration_s=4.0))
        assert _png_size(out_dir / "rec_0123456789abcdef.waveform.png") == WAVEFORM_SIZE_PX


class TestVerbatimMetrics:
    """The title states the quality stage's numbers and nothing else — no flags, no prompt."""

    def test_title_states_peak_and_rms_from_the_record(self) -> None:
        rendered = title(RECORDING, METRICS)
        assert "peak (orig) -3.01 dBFS" in rendered
        assert "RMS (active) -18.00 dBFS" in rendered

    def test_title_identifies_the_recording(self) -> None:
        rendered = title(RECORDING, METRICS)
        for value in (RECORDING.recording_id, RECORDING.speaker_id, RECORDING.session_id):
            assert value in rendered

    def test_title_states_duration_from_the_record(self) -> None:
        assert "0.500 s" in title(RECORDING, METRICS)

    def test_title_carries_no_flag(self) -> None:
        flagged = QualityMetrics(**{**vars(METRICS), "flags": ("clipping", "low_volume")})
        rendered = title(RECORDING, flagged)
        assert "clipping" not in rendered
        assert "low_volume" not in rendered

    def test_title_carries_no_prompt_text(self) -> None:
        assert RECORDING.prompt_text not in title(RECORDING, METRICS)

    def test_levels_are_never_recomputed_from_the_samples(self, tmp_path: Path) -> None:
        # The metrics deliberately contradict the audio: a -18 dBFS tone described as -47.75 peak.
        # A stage measuring the samples it plots could not produce this title (ADR-0011/ADR-0012).
        contradicting = QualityMetrics(
            **{**vars(METRICS), "peak_dbfs": -47.75, "active_rms_dbfs": -60.25}
        )
        rendered = title(RECORDING, contradicting)
        assert "peak (orig) -47.75 dBFS" in rendered
        assert "RMS (active) -60.25 dBFS" in rendered

    def test_the_module_reads_no_quality_math(self) -> None:
        # The structural half of the same claim: whatever the image module imports, it is not the
        # functions that measure. Anything it could call to recompute a level is absent.
        import sdw.images as images

        assert not [name for name in vars(images) if name.startswith(("_rms", "_dbfs", "measure"))]


class TestAbsoluteScales:
    """Fixed axes: level is visible, so an Image can never contradict a Quality flag."""

    def test_waveform_y_axis_is_fixed_at_full_scale(self) -> None:
        assert WAVEFORM_YLIM == (-1.0, 1.0)

    def test_spectrogram_db_range_is_fixed(self) -> None:
        assert DB_RANGE == (-80.0, 0.0)

    def test_a_quiet_waveform_does_not_look_like_a_loud_one(self, tmp_path: Path) -> None:
        loud = _render(tmp_path / "loud", audio=_audio(tmp_path / "loud.wav", amp_dbfs=-6.0))
        quiet = _render(tmp_path / "quiet", audio=_audio(tmp_path / "quiet.wav", amp_dbfs=-45.0))
        name = "rec_0123456789abcdef.waveform.png"
        assert (loud / name).read_bytes() != (quiet / name).read_bytes()

    def test_a_quiet_spectrogram_does_not_look_like_a_loud_one(self, tmp_path: Path) -> None:
        loud = _render(tmp_path / "loud", audio=_audio(tmp_path / "loud.wav", amp_dbfs=-6.0))
        quiet = _render(tmp_path / "quiet", audio=_audio(tmp_path / "quiet.wav", amp_dbfs=-45.0))
        name = "rec_0123456789abcdef.spectrogram.png"
        assert (loud / name).read_bytes() != (quiet / name).read_bytes()

    def test_silence_renders_without_error(self, tmp_path: Path) -> None:
        # The degenerate signal: an all-zero Recording floors every dB value. It must still render
        # (coverage is unconditional) rather than produce a NaN axis or a crash.
        path = tmp_path / "silent.wav"
        synth.silence(path, duration_s=0.5)
        out_dir = _render(tmp_path, audio=normalize(path))
        assert len(list(out_dir.iterdir())) == 2


class TestDeterminism:
    """Same machine, same input, same bytes — what ADR-0008's build-twice-and-diff rests on."""

    def test_rendering_twice_is_byte_identical(self, tmp_path: Path) -> None:
        audio = _audio(tmp_path / "a.wav")
        first = _render(tmp_path / "first", audio=audio)
        second = _render(tmp_path / "second", audio=audio)
        for path in first.iterdir():
            assert path.read_bytes() == (second / path.name).read_bytes()

    def test_no_software_chunk_names_the_renderer(self, tmp_path: Path) -> None:
        out_dir = _render(tmp_path)
        for path in out_dir.iterdir():
            assert b"Software" not in path.read_bytes()

    def test_a_user_rcparams_cannot_change_the_output(self, tmp_path: Path) -> None:
        import matplotlib

        audio = _audio(tmp_path / "a.wav")
        first = _render(tmp_path / "first", audio=audio)
        with matplotlib.rc_context({"figure.dpi": 33, "font.size": 22, "axes.grid": True}):
            second = _render(tmp_path / "second", audio=audio)
        for path in first.iterdir():
            assert path.read_bytes() == (second / path.name).read_bytes()


class TestFailure:
    """A render error is a tool bug, so it aborts the build rather than skipping a Recording."""

    def test_an_unwritable_destination_is_a_hard_error(self, tmp_path: Path) -> None:
        audio = _audio(tmp_path / "a.wav")
        blocker = tmp_path / "images"
        blocker.write_text("not a directory")
        with pytest.raises(HardError):
            render(audio, METRICS, RECORDING, blocker)
