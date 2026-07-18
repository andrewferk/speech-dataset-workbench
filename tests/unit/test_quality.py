"""The quality metrics, the three flags, and the human digest (#26, ADR-0007).

The stage measures and never decides: every metric here is descriptive, a flag is advisory, and
nothing in this module can drop a Recording or change an exit code. These tests pin the four
checks against signals whose properties are known by construction (`tests.synth`), the fixed
constants that make a check *mean* something (the -120 floor, the 3-sample / 0.99 FS clip run,
the 20 ms frame, the 0.2 s guard), the exactly-three flag vocabulary, and the digest's shape.

Two splits are load-bearing and get their own assertions: clipping is measured on the *Original*
floats — so a clipped channel that the downmix averages away still flags — and everything else is
measured on the Normalized.
"""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sdw.config import QualityConfig
from sdw.normalize import normalize
from sdw.quality import (
    CLIP_RUN_MIN,
    CLIP_THRESHOLD,
    DBFS_FLOOR,
    FLAG_CLIPPING,
    FLAG_DURATION_OUT_OF_RANGE,
    FLAG_LOW_VOLUME,
    FLAGS,
    MIN_SILENCE_RUN_S,
    SILENCE_FRAME_S,
    QualityMetrics,
    measure,
    render_digest,
)
from tests import synth

DEFAULTS = QualityConfig()


def _measure(path: Path, config: QualityConfig = DEFAULTS) -> QualityMetrics:
    return measure(normalize(path), config)


def _write(path: Path, mono: np.ndarray, *, sample_rate: int = 16000) -> Path:
    """Write float samples verbatim as a 16-bit PCM WAV — for signals synth does not name."""
    sf.write(path, mono, sample_rate, subtype="PCM_16")
    return path


def _tone(path: Path, **kwargs: float) -> Path:
    defaults = dict(
        freq_hz=400.0, amp_dbfs=-18.0, duration_s=1.0, sample_rate=16000, bit_depth=16, channels=1
    )
    synth.write_wav(path, **{**defaults, **kwargs})  # type: ignore[arg-type]
    return path


class TestFixedConstants:
    """What a check *means* is not tunable — two configs cannot disagree about "clipped"."""

    def test_constants_match_the_adr(self) -> None:
        assert DBFS_FLOOR == -120.0
        assert (CLIP_RUN_MIN, CLIP_THRESHOLD) == (3, 0.99)
        assert (SILENCE_FRAME_S, MIN_SILENCE_RUN_S) == (0.02, 0.2)

    def test_flag_vocabulary_is_exactly_three(self) -> None:
        assert FLAGS == (FLAG_CLIPPING, FLAG_LOW_VOLUME, FLAG_DURATION_OUT_OF_RANGE)
        assert FLAGS == ("clipping", "low_volume", "duration_out_of_range")


class TestClipping:
    def test_clean_tone_does_not_clip(self, tmp_path: Path) -> None:
        metrics = _measure(_tone(tmp_path / "a.wav"))
        assert metrics.clip_ratio == 0.0
        assert FLAG_CLIPPING not in metrics.flags

    def test_flat_top_run_trips_the_flag(self, tmp_path: Path) -> None:
        synth.clipped(tmp_path / "a.wav", duration_s=1.0)
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.clip_ratio > 0.0
        assert FLAG_CLIPPING in metrics.flags
        assert metrics.peak_dbfs == pytest.approx(0.0, abs=0.01)

    def test_a_run_shorter_than_three_samples_is_not_clipping(self, tmp_path: Path) -> None:
        # Two samples at full scale in an otherwise quiet signal: a transient, not a flat top.
        mono = np.full(16000, 0.5)
        mono[100:102] = 1.0
        metrics = _measure(_write(tmp_path / "a.wav", mono))
        assert metrics.clip_ratio == 0.0
        assert FLAG_CLIPPING not in metrics.flags

    def test_exactly_three_samples_is_clipping(self, tmp_path: Path) -> None:
        mono = np.full(16000, 0.5)
        mono[100:103] = 1.0
        metrics = _measure(_write(tmp_path / "a.wav", mono))
        assert metrics.clip_ratio == pytest.approx(3 / 16000)
        assert FLAG_CLIPPING in metrics.flags

    def test_clip_ratio_counts_only_run_samples(self, tmp_path: Path) -> None:
        # One 4-sample run plus a lone full-scale sample: the singleton belongs to no run.
        mono = np.full(16000, 0.5)
        mono[100:104] = 1.0
        mono[900] = 1.0
        assert _measure(_write(tmp_path / "a.wav", mono)).clip_ratio == pytest.approx(4 / 16000)

    def test_measured_on_the_original_not_the_normalized(self, tmp_path: Path) -> None:
        # A clipped left channel against a silent right: the downmix halves the flat top to 0.5,
        # so a check reading the Normalized would see nothing. Per-channel on the Original does.
        left = np.clip(2.0 * np.sin(2.0 * np.pi * 440.0 * np.arange(16000) / 16000), -1.0, 1.0)
        stereo = np.column_stack([left, np.zeros(16000)])
        _write(tmp_path / "a.wav", stereo)
        audio = normalize(tmp_path / "a.wav")
        assert np.max(np.abs(audio.samples)) < CLIP_THRESHOLD
        assert FLAG_CLIPPING in measure(audio, DEFAULTS).flags

    def test_multichannel_ratio_spans_every_channel(self, tmp_path: Path) -> None:
        left = np.full(16000, 0.5)
        left[100:104] = 1.0
        stereo = np.column_stack([left, np.full(16000, 0.5)])
        metrics = _measure(_write(tmp_path / "a.wav", stereo))
        # 4 clipped samples out of 16000 frames x 2 channels.
        assert metrics.clip_ratio == pytest.approx(4 / 32000)


class TestSilence:
    def test_silence_never_raises_a_flag(self, tmp_path: Path) -> None:
        synth.leading_trailing_silence(
            tmp_path / "a.wav", lead_s=1.0, tone_s=1.0, trail_s=1.0, amp_dbfs=-18.0
        )
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.silence_ratio > 0.0
        assert metrics.flags == ()

    def test_leading_and_trailing_runs_are_measured(self, tmp_path: Path) -> None:
        synth.leading_trailing_silence(
            tmp_path / "a.wav", lead_s=0.5, tone_s=1.0, trail_s=0.4, amp_dbfs=-18.0
        )
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.leading_silence_s == pytest.approx(0.5, abs=SILENCE_FRAME_S)
        assert metrics.trailing_silence_s == pytest.approx(0.4, abs=SILENCE_FRAME_S)

    def test_a_run_under_the_guard_is_not_counted(self, tmp_path: Path) -> None:
        # 0.1 s of head silence is a natural pause, below the 0.2 s D_min guard.
        synth.leading_trailing_silence(
            tmp_path / "a.wav", lead_s=0.1, tone_s=1.0, trail_s=0.0, amp_dbfs=-18.0
        )
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.leading_silence_s == 0.0
        assert metrics.trailing_silence_s == 0.0

    def test_silence_ratio_is_frames_over_frames(self, tmp_path: Path) -> None:
        synth.leading_trailing_silence(
            tmp_path / "a.wav", lead_s=1.0, tone_s=1.0, trail_s=0.0, amp_dbfs=-18.0
        )
        assert _measure(tmp_path / "a.wav").silence_ratio == pytest.approx(0.5, abs=0.02)

    def test_a_wholly_silent_recording_is_all_silence(self, tmp_path: Path) -> None:
        synth.silence(tmp_path / "a.wav", duration_s=1.0)
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.silence_ratio == 1.0
        assert metrics.leading_silence_s == pytest.approx(1.0)
        assert metrics.trailing_silence_s == pytest.approx(1.0)


class TestLowVolume:
    def test_a_clean_level_clears_the_flag(self, tmp_path: Path) -> None:
        metrics = _measure(_tone(tmp_path / "a.wav", amp_dbfs=-18.0))
        assert metrics.active_rms_dbfs == pytest.approx(-18.0, abs=0.1)
        assert FLAG_LOW_VOLUME not in metrics.flags

    def test_a_quiet_recording_trips_the_flag(self, tmp_path: Path) -> None:
        # -35 dBFS is audible (above the -40 silence threshold) but below the -30 low_volume knob.
        metrics = _measure(_tone(tmp_path / "a.wav", amp_dbfs=-35.0))
        assert metrics.active_rms_dbfs == pytest.approx(-35.0, abs=0.5)
        assert FLAG_LOW_VOLUME in metrics.flags

    def test_a_recording_quieter_than_the_silence_threshold_floors(self, tmp_path: Path) -> None:
        # A tone below `silence_threshold_dbfs` everywhere leaves no active frame, so the
        # active-region RMS floors to -120 exactly as a wholly-silent one does. That is the
        # intended reading: nothing in this Recording rose above the silence floor.
        metrics = _measure(_tone(tmp_path / "a.wav", amp_dbfs=-45.0))
        assert metrics.active_rms_dbfs == DBFS_FLOOR
        assert FLAG_LOW_VOLUME in metrics.flags

    def test_rms_is_the_raw_convention_with_no_aes17_offset(self, tmp_path: Path) -> None:
        # A full-scale sine reads ~= -3 dBFS under raw 20*log10, not 0 dBFS.
        mono = 0.999 * np.sin(2.0 * np.pi * 400.0 * np.arange(16000) / 16000)
        metrics = _measure(_write(tmp_path / "a.wav", mono))
        assert metrics.active_rms_dbfs == pytest.approx(-3.01, abs=0.05)

    def test_measured_over_the_active_region_only(self, tmp_path: Path) -> None:
        # Padding a -18 dBFS tone with silence must not drag the reported level down: the
        # measurement trims to the active region (the audio itself is never trimmed).
        synth.leading_trailing_silence(
            tmp_path / "a.wav", lead_s=2.0, tone_s=1.0, trail_s=2.0, amp_dbfs=-18.0
        )
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.active_rms_dbfs == pytest.approx(-18.0, abs=0.5)
        assert FLAG_LOW_VOLUME not in metrics.flags

    def test_a_wholly_silent_recording_floors_and_trips(self, tmp_path: Path) -> None:
        synth.silence(tmp_path / "a.wav", duration_s=1.0)
        metrics = _measure(tmp_path / "a.wav")
        assert metrics.active_rms_dbfs == DBFS_FLOOR
        assert metrics.peak_dbfs == DBFS_FLOOR
        assert FLAG_LOW_VOLUME in metrics.flags

    def test_the_threshold_is_a_knob(self, tmp_path: Path) -> None:
        path = _tone(tmp_path / "a.wav", amp_dbfs=-35.0)
        assert FLAG_LOW_VOLUME not in _measure(path, QualityConfig(low_volume_rms_dbfs=-60.0)).flags


class TestDuration:
    def test_a_normal_duration_clears_the_flag(self, tmp_path: Path) -> None:
        metrics = _measure(_tone(tmp_path / "a.wav", duration_s=2.0))
        assert metrics.duration_s == pytest.approx(2.0)
        assert FLAG_DURATION_OUT_OF_RANGE not in metrics.flags

    def test_a_blip_is_flagged_not_dropped(self, tmp_path: Path) -> None:
        metrics = _measure(_tone(tmp_path / "a.wav", duration_s=0.1))
        assert metrics.duration_s == pytest.approx(0.1)
        assert FLAG_DURATION_OUT_OF_RANGE in metrics.flags

    def test_a_runaway_is_flagged(self, tmp_path: Path) -> None:
        metrics = _measure(_tone(tmp_path / "a.wav", duration_s=25.0))
        assert FLAG_DURATION_OUT_OF_RANGE in metrics.flags

    def test_duration_is_normalized_frames_over_16000(self, tmp_path: Path) -> None:
        # A 48 kHz Original: the duration describes what the Sample ships, not the Original.
        metrics = _measure(_tone(tmp_path / "a.wav", duration_s=2.0, sample_rate=48000))
        assert metrics.duration_s == pytest.approx(2.0, abs=0.001)

    def test_the_bounds_are_knobs(self, tmp_path: Path) -> None:
        path = _tone(tmp_path / "a.wav", duration_s=0.1)
        loose = QualityConfig(duration_min_s=0.05)
        assert FLAG_DURATION_OUT_OF_RANGE not in _measure(path, loose).flags


class TestFlagsTogether:
    def test_a_clean_recording_carries_no_flags(self, tmp_path: Path) -> None:
        assert _measure(_tone(tmp_path / "a.wav", duration_s=2.0)).flags == ()

    def test_flags_come_in_the_fixed_vocabulary_order(self, tmp_path: Path) -> None:
        # Clipped *and* far too long: two flags, in vocabulary order regardless of check order.
        synth.clipped(tmp_path / "a.wav", duration_s=25.0)
        assert _measure(tmp_path / "a.wav").flags == (FLAG_CLIPPING, FLAG_DURATION_OUT_OF_RANGE)


class TestDigest:
    def _metrics(self, **overrides: object) -> QualityMetrics:
        base = dict(
            duration_s=2.0,
            peak_dbfs=-6.0,
            clip_ratio=0.0,
            active_rms_dbfs=-18.0,
            leading_silence_s=0.0,
            trailing_silence_s=0.0,
            silence_ratio=0.0,
            flags=(),
        )
        return QualityMetrics(**{**base, **overrides})  # type: ignore[arg-type]

    def test_tally_counts_clean_and_flagged(self) -> None:
        digest = render_digest(
            [
                ("rec_1", self._metrics()),
                ("rec_2", self._metrics(flags=(FLAG_CLIPPING,))),
                ("rec_3", self._metrics(flags=(FLAG_CLIPPING, FLAG_LOW_VOLUME))),
            ]
        )
        assert "Quality: 3 recordings — 1 clean, 2 flagged" in digest
        assert "clipping" in digest and "low_volume" in digest

    def test_clean_recordings_are_omitted_from_the_flagged_list(self) -> None:
        digest = render_digest([("rec_clean", self._metrics())])
        assert "rec_clean" not in digest
        assert "Flagged:" not in digest

    def test_a_flagged_recording_gets_a_line_with_its_evidence(self) -> None:
        digest = render_digest(
            [
                (
                    "rec_abc",
                    self._metrics(flags=(FLAG_CLIPPING,), clip_ratio=0.00312, peak_dbfs=-0.02),
                )
            ]
        )
        assert "rec_abc" in digest
        assert "peak=-0.02dBFS" in digest
        assert "clip_ratio=0.0031" in digest

    def test_evidence_keeps_trailing_zeros_so_the_column_scans(self) -> None:
        # Fixed decimal places, not `round` — an exactly-full-scale peak is "0.00", not "0.0".
        digest = render_digest(
            [("rec_x", self._metrics(flags=(FLAG_CLIPPING,), peak_dbfs=0.0, clip_ratio=0.5))]
        )
        assert "peak=0.00dBFS" in digest
        assert "clip_ratio=0.5000" in digest

    def test_low_volume_and_duration_lines_state_their_evidence(self) -> None:
        digest = render_digest(
            [
                ("rec_q", self._metrics(flags=(FLAG_LOW_VOLUME,), active_rms_dbfs=-33.84)),
                ("rec_s", self._metrics(flags=(FLAG_DURATION_OUT_OF_RANGE,), duration_s=0.31264)),
            ]
        )
        assert "active_rms=-33.84dBFS" in digest
        assert "duration=0.313s" in digest

    def test_an_empty_dataset_still_renders(self) -> None:
        assert "Quality: 0 recordings — 0 clean, 0 flagged" in render_digest([])

    def test_the_digest_is_deterministic(self) -> None:
        rows = [("rec_b", self._metrics(flags=(FLAG_CLIPPING,))), ("rec_a", self._metrics())]
        assert render_digest(rows) == render_digest(rows)
