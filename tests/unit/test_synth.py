"""The fixture generator is itself a tested unit (ADR-0008).

Every claim ``tests/synth.py`` makes about the audio it writes — level, duration, rate, depth,
channels, a genuine clipped flat-top, silence, and the degenerate abort inputs — is checked
here by reading the bytes back, because every downstream golden and diff stands on it.
"""

from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
import soundfile as sf

from tests import synth


def _longest_run_at_full_scale(s: npt.NDArray[np.float64], threshold: float = 0.99) -> int:
    """The longest run of consecutive samples with ``|s| >= threshold`` — a clip run (ADR-0007)."""
    best = current = 0
    for above in np.abs(s) >= threshold:
        current = current + 1 if above else 0
        best = max(best, current)
    return best


def _rms_dbfs(s: npt.NDArray[np.float64]) -> float:
    return float(20.0 * np.log10(np.sqrt(np.mean(s**2))))


class TestWriteWav:
    def test_writes_the_requested_format(self, tmp_path: Path) -> None:
        path = tmp_path / "tone.wav"
        synth.write_wav(
            path,
            freq_hz=400.0,
            amp_dbfs=-18.0,
            duration_s=2.0,
            sample_rate=48000,
            bit_depth=24,
            channels=2,
        )
        info = sf.info(path)
        assert info.samplerate == 48000
        assert info.channels == 2
        assert info.subtype == "PCM_24"
        assert info.frames == 96000

    def test_tone_lands_at_the_requested_rms(self, tmp_path: Path) -> None:
        # Integer cycles (400 Hz x 2.0 s) make the RMS exact: amp_dbfs *is* active_rms_dbfs.
        path = tmp_path / "tone.wav"
        synth.write_wav(
            path,
            freq_hz=400.0,
            amp_dbfs=-18.0,
            duration_s=2.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        data, _ = sf.read(path, dtype="float64")
        assert _rms_dbfs(data) == pytest.approx(-18.0, abs=0.01)

    def test_seed_yields_reproducible_noise(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a.wav", tmp_path / "b.wav"
        for path in (a, b):
            synth.write_wav(
                path,
                freq_hz=440.0,
                amp_dbfs=-20.0,
                duration_s=1.0,
                sample_rate=16000,
                bit_depth=16,
                channels=1,
                seed=7,
            )
        assert a.read_bytes() == b.read_bytes()
        data, _ = sf.read(a, dtype="float64")
        # Noise is non-tonal but still parked at the requested RMS.
        assert _rms_dbfs(data) == pytest.approx(-20.0, abs=0.1)

    def test_rejects_unknown_bit_depth(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="bit_depth"):
            synth.write_wav(
                tmp_path / "x.wav",
                freq_hz=440.0,
                amp_dbfs=-18.0,
                duration_s=1.0,
                sample_rate=16000,
                bit_depth=8,
                channels=1,
            )


class TestShortcuts:
    def test_silence_is_all_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "silence.wav"
        synth.silence(path, duration_s=1.0)
        data, sr = sf.read(path, dtype="float64")
        assert sr == 16000
        assert data.shape == (16000,)
        assert not np.any(data)

    @pytest.mark.parametrize("bit_depth", [16, 24, 32])
    def test_clipped_has_a_genuine_flat_top(self, tmp_path: Path, bit_depth: int) -> None:
        # A real clip run (>= 3 consecutive samples at >= 0.99 FS), not a scaled sine that
        # merely grazes full scale for one sample per cycle — and it holds at every bit depth.
        path = tmp_path / f"clipped_{bit_depth}.wav"
        synth.clipped(path, duration_s=1.0, bit_depth=bit_depth)
        data, _ = sf.read(path, dtype="float64")
        assert _longest_run_at_full_scale(data) >= 3
        assert np.max(np.abs(data)) == pytest.approx(1.0, abs=1e-3)

    def test_leading_trailing_silence_frames_the_tone(self, tmp_path: Path) -> None:
        path = tmp_path / "padded.wav"
        synth.leading_trailing_silence(path, lead_s=0.3, tone_s=1.0, trail_s=0.25)
        data, sr = sf.read(path, dtype="float64")
        assert sr == 16000
        assert data.shape == (int(1.55 * 16000),)
        lead, trail = int(0.3 * 16000), int(0.25 * 16000)
        assert not np.any(data[:lead])  # silent head
        assert not np.any(data[-trail:])  # silent tail
        assert np.any(data[lead:-trail])  # active middle


class TestAbortInputs:
    def test_non_wav_bytes_do_not_decode(self, tmp_path: Path) -> None:
        path = tmp_path / "not_really.wav"
        synth.write_non_wav(path)
        assert path.read_bytes()  # the file exists and is non-empty...
        with pytest.raises(sf.SoundFileError):  # ...but soundfile cannot decode it
            sf.read(path)

    def test_truncated_wav_does_not_decode(self, tmp_path: Path) -> None:
        path = tmp_path / "cut_short.wav"
        synth.write_truncated_wav(path)
        assert path.read_bytes().startswith(b"RIFF")  # a real WAV's opening bytes...
        with pytest.raises(sf.SoundFileError):  # ...cut off mid-header, so the decode fails
            sf.read(path)

    def test_zero_frame_wav_is_valid_but_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.wav"
        synth.write_zero_frame_wav(path)
        info = sf.info(path)  # a valid header...
        assert info.frames == 0  # ...describing no samples
        data, _ = sf.read(path, dtype="float64")
        assert data.shape == (0,)
