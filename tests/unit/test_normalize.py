"""In-memory normalization to mono / 16 kHz / 16-bit PCM WAV (#25, ADR-0005).

The stage is a pure function of an Original's bytes: decode to float64, downmix by arithmetic
mean, resample to 16 kHz with soxr ``HQ``, and hand the caller both the Normalized samples and the
*decoded Original* — the tap the clipping check reads (#25). Writing is a separate call, so
``validate`` normalizes and discards. These tests pin the target format, the four input paths
(passthrough, resample, downmix, depth), the "no gain, no loudness change" promise, the decode
gate (non-WAV / corrupt / truncated / zero-frame abort), that Originals are never touched, and
byte-identical output for the same input bytes.
"""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sdw.errors import HardError
from sdw.normalize import TARGET_SAMPLE_RATE, TARGET_SUBTYPE, normalize, write_normalized
from tests import synth

# A level parked well clear of full scale and of the quality knobs, and an integer number of tone
# cycles per second, so every assertion below is about normalization rather than about rounding.
AMP_DBFS = -18.0
FREQ_HZ = 400.0


def _original(
    path: Path,
    *,
    sample_rate: int = 16000,
    channels: int = 1,
    bit_depth: int = 16,
    duration_s: float = 1.0,
) -> Path:
    synth.write_wav(
        path,
        freq_hz=FREQ_HZ,
        amp_dbfs=AMP_DBFS,
        duration_s=duration_s,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        channels=channels,
    )
    return path


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


class TestTarget:
    def test_constants_are_the_asr_convention(self) -> None:
        assert TARGET_SAMPLE_RATE == 16000
        assert TARGET_SUBTYPE == "PCM_16"

    def test_samples_are_mono_float64_at_16k(self, tmp_path: Path) -> None:
        audio = normalize(_original(tmp_path / "a.wav", sample_rate=48000, channels=2))
        assert audio.samples.ndim == 1
        assert audio.samples.dtype == np.float64
        assert audio.sample_rate == TARGET_SAMPLE_RATE

    def test_written_file_is_mono_16k_pcm16(self, tmp_path: Path) -> None:
        audio = normalize(_original(tmp_path / "a.wav", sample_rate=48000, channels=2))
        out = tmp_path / "out.wav"
        write_normalized(audio, out)
        info = sf.info(out)
        assert (info.samplerate, info.channels, info.subtype) == (16000, 1, "PCM_16")


class TestInputPaths:
    def test_already_16k_mono_passes_through_unresampled(self, tmp_path: Path) -> None:
        # No soxr in the loop at all: the Normalized frame count equals the Original's exactly,
        # and the samples are the decoded Original itself (ADR-0005 skips step 3 at 16 kHz).
        original = _original(tmp_path / "a.wav", sample_rate=16000, channels=1)
        audio = normalize(original)
        decoded, _ = sf.read(original, dtype="float64")
        assert audio.samples.shape == decoded.shape
        assert np.array_equal(audio.samples, decoded)

    def test_16k_roundtrip_is_bit_exact_through_pcm16(self, tmp_path: Path) -> None:
        # A conforming Original is not put through a lossy round-trip: the written bytes decode
        # back to the very samples that went in.
        original = _original(tmp_path / "a.wav", sample_rate=16000, channels=1)
        out = tmp_path / "out.wav"
        write_normalized(normalize(original), out)
        written, _ = sf.read(out, dtype="float64")
        decoded, _ = sf.read(original, dtype="float64")
        assert np.array_equal(written, decoded)

    def test_resamples_48k_to_16k(self, tmp_path: Path) -> None:
        audio = normalize(_original(tmp_path / "a.wav", sample_rate=48000, duration_s=2.0))
        assert audio.sample_rate == 16000
        # Duration is preserved: 2 s at 16 kHz, within a frame of soxr's boundary handling.
        assert abs(len(audio.samples) - 32000) <= 1

    def test_downmixes_by_arithmetic_mean(self, tmp_path: Path) -> None:
        # synth tiles identical channels, so the mean equals the channel — a stereo Original
        # normalizes to exactly what the same mono Original does.
        stereo = normalize(_original(tmp_path / "s.wav", channels=2))
        mono = normalize(_original(tmp_path / "m.wav", channels=1))
        assert np.array_equal(stereo.samples, mono.samples)

    def test_downmix_is_the_mean_not_the_sum(self, tmp_path: Path) -> None:
        # Two channels that differ: the left is the tone, the right is silence. The mean halves
        # the level (-6 dB); a sum would leave it unchanged and could clip.
        path = tmp_path / "a.wav"
        tone, _ = sf.read(_original(tmp_path / "tone.wav"), dtype="float64")
        sf.write(path, np.column_stack([tone, np.zeros_like(tone)]), 16000, subtype="PCM_16")
        audio = normalize(path)
        assert audio.samples == pytest.approx(tone / 2.0, abs=1e-12)

    def test_reduces_bit_depth_to_16(self, tmp_path: Path) -> None:
        audio = normalize(_original(tmp_path / "a.wav", bit_depth=24))
        out = tmp_path / "out.wav"
        write_normalized(audio, out)
        assert sf.info(out).subtype == "PCM_16"


class TestNoLoudnessChange:
    def test_level_is_unchanged_by_normalization(self, tmp_path: Path) -> None:
        # No gain, no loudness change: what the quality checks measure is what was recorded.
        original = _original(tmp_path / "a.wav", sample_rate=48000)
        audio = normalize(original)
        decoded, _ = sf.read(original, dtype="float64")
        assert 20 * np.log10(_rms(audio.samples)) == pytest.approx(AMP_DBFS, abs=0.05)
        assert _rms(audio.samples) == pytest.approx(_rms(decoded), rel=1e-3)

    def test_quiet_audio_is_not_lifted(self, tmp_path: Path) -> None:
        # A peak normalizer would drag this up to full scale; a faithful one leaves it at -40.
        synth.write_wav(
            tmp_path / "a.wav",
            freq_hz=FREQ_HZ,
            amp_dbfs=-40.0,
            duration_s=1.0,
            sample_rate=16000,
            bit_depth=16,
            channels=1,
        )
        audio = normalize(tmp_path / "a.wav")
        assert 20 * np.log10(_rms(audio.samples)) == pytest.approx(-40.0, abs=0.05)

    def test_silence_stays_silent(self, tmp_path: Path) -> None:
        # No dither: a digitally-silent Original normalizes to exact zeros, not a noise floor.
        synth.silence(tmp_path / "a.wav", duration_s=0.5)
        assert not np.any(normalize(tmp_path / "a.wav").samples)


class TestOriginalTap:
    """The decoded Original float64 is exposed at this seam for the clipping check (#25)."""

    def test_exposes_the_decoded_original_samples(self, tmp_path: Path) -> None:
        original = _original(tmp_path / "a.wav", sample_rate=48000, channels=2)
        audio = normalize(original)
        decoded, rate = sf.read(original, dtype="float64")
        assert np.array_equal(audio.original, decoded)
        assert audio.original_sample_rate == rate == 48000

    def test_original_tap_is_pre_downmix_and_pre_resample(self, tmp_path: Path) -> None:
        # The tap must be the Original's own samples, not the Normalized ones: a clip that the
        # downmix would average away is still visible here.
        path = tmp_path / "a.wav"
        tone, _ = sf.read(_original(tmp_path / "tone.wav"), dtype="float64")
        sf.write(
            path,
            np.column_stack([np.ones_like(tone), np.zeros_like(tone)]),
            48000,
            subtype="PCM_16",
        )
        audio = normalize(path)
        assert audio.original.shape == (len(tone), 2)
        assert audio.original.max() >= 0.99
        assert audio.original.max() > audio.samples.max()

    def test_tap_is_the_same_decode_not_a_second_read(self, tmp_path: Path) -> None:
        # A measurement tap, not a second decode: normalizing opens the Original exactly once.
        original = _original(tmp_path / "a.wav", sample_rate=48000)
        opened = []
        real_open = sf.SoundFile

        def counting_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
            opened.append(file)
            return real_open(file, *args, **kwargs)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr("sdw.normalize.sf.SoundFile", counting_open)
            normalize(original)
        assert len(opened) == 1


class TestDecodeGate:
    """Decodability is the ingest gate: if it does not decode, the build aborts (ADR-0005)."""

    def test_non_wav_aborts(self, tmp_path: Path) -> None:
        synth.write_non_wav(tmp_path / "a.wav")
        with pytest.raises(HardError, match="cannot decode"):
            normalize(tmp_path / "a.wav")

    def test_a_decodable_non_wav_aborts(self, tmp_path: Path) -> None:
        # v0.1 ingests WAV only, so decodability alone is not enough: a FLAC under a `.wav` name
        # decodes fine and is still rejected (ADR-0005).
        synth.write_wrong_container(tmp_path / "a.wav")
        with pytest.raises(HardError, match="not a WAV"):
            normalize(tmp_path / "a.wav")

    def test_a_float_subtype_wav_is_accepted(self, tmp_path: Path) -> None:
        # The gate is the container, not the subtype: a float WAV is a normal export, and it is
        # a WAV, so it is data. It normalizes to the same float64 as any other Original.
        path = tmp_path / "a.wav"
        tone, _ = sf.read(_original(tmp_path / "tone.wav"), dtype="float64")
        sf.write(path, tone, 16000, subtype="FLOAT")
        assert normalize(path).samples == pytest.approx(tone, abs=1e-7)

    def test_truncated_wav_aborts(self, tmp_path: Path) -> None:
        synth.write_truncated_wav(tmp_path / "a.wav")
        with pytest.raises(HardError, match="cannot decode"):
            normalize(tmp_path / "a.wav")

    def test_zero_frame_wav_aborts(self, tmp_path: Path) -> None:
        synth.write_zero_frame_wav(tmp_path / "a.wav")
        with pytest.raises(HardError, match="zero frames"):
            normalize(tmp_path / "a.wav")

    def test_missing_file_aborts(self, tmp_path: Path) -> None:
        with pytest.raises(HardError):
            normalize(tmp_path / "absent.wav")

    def test_a_decodable_but_bad_signal_is_not_an_abort(self, tmp_path: Path) -> None:
        # Silent and clipped audio decode fine, so they are soft quality flags (ADR-0007), never
        # an ingest error. Normalization is where that line is drawn, so pin it here.
        synth.silence(tmp_path / "silent.wav", duration_s=1.0)
        synth.clipped(tmp_path / "clipped.wav")
        assert len(normalize(tmp_path / "silent.wav").samples) == 16000
        assert len(normalize(tmp_path / "clipped.wav").samples) == 16000


class TestOriginalsAreUntouched:
    def test_normalizing_does_not_modify_the_original(self, tmp_path: Path) -> None:
        original = _original(tmp_path / "a.wav", sample_rate=48000, channels=2)
        before = original.read_bytes()
        stat_before = original.stat().st_mtime_ns
        normalize(original)
        assert original.read_bytes() == before
        assert original.stat().st_mtime_ns == stat_before

    def test_writing_does_not_add_anything_beside_the_original(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        original = _original(data_in / "a.wav", sample_rate=48000)
        write_normalized(normalize(original), tmp_path / "out.wav")
        assert [p.name for p in data_in.iterdir()] == ["a.wav"]


class TestDeterminism:
    def test_same_bytes_give_byte_identical_output(self, tmp_path: Path) -> None:
        # Same input bytes + same tool version on this architecture -> byte-identical Normalized
        # WAV (ADR-0005). Cross-architecture bit-exactness is explicitly not claimed.
        source = _original(tmp_path / "a.wav", sample_rate=48000, channels=2)
        copy = tmp_path / "b.wav"
        copy.write_bytes(source.read_bytes())

        first, second = tmp_path / "1.wav", tmp_path / "2.wav"
        write_normalized(normalize(source), first)
        write_normalized(normalize(copy), second)
        assert first.read_bytes() == second.read_bytes()

    def test_repeated_normalization_is_stable(self, tmp_path: Path) -> None:
        original = _original(tmp_path / "a.wav", sample_rate=44100, channels=2)
        assert np.array_equal(normalize(original).samples, normalize(original).samples)
