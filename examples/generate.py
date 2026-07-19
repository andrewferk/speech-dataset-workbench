"""Write the committed example ``--data-in`` (ADR-0009).

The corpus an operator builds on their first run, before supplying any audio of their own:
``examples/data-in/`` ships a ``recordings.csv`` and twelve WAVs, so ``build --data-in
examples/data-in`` works straight out of a clone with no downloads. The audio is generated
tones, not speech — ADR-0009 requires an ``examples/README.md`` to say so plainly and up front,
and #35 writes it from this corpus's observed output — while the Prompts stay honest English
sentences, because a Prompt that described its own tone would teach a wrong mental model of what
a Prompt is.

Tone-writing itself lives in :mod:`tests.synth`, the single source of fixture truth (ADR-0008);
this module contributes only the *shape*. That shape is chosen to teach, one Recording at a time:

- **4 Sessions across 2 Speakers.** Four clears ADR-0004's >= 3-Session floor, so `val` and `test`
  each receive a real Session and the first run never prints the produce-and-flag warning. Two
  Speakers fire the report-only speaker-overlap note, which is how the reader learns that
  disjointness is Session-level, not Speaker-level.
- **One Prompt recorded twice within one Session.** `(Session, Prompt)` is not unique and all
  attempts are data (ADR-0001) — visible in the corpus rather than asserted in prose. The two
  takes differ in signal, so they are not byte-identical and do not collapse to one Recording
  (ADR-0001/ADR-0013): two attempts, two Samples.
- **Exactly one Recording below the -30 dBFS knob.** It trips `low_volume` and *stays in the
  Manifest*, which is ADR-0007's included-and-flagged policy demonstrating itself. One flag keeps
  the signal readable; three would read as a broken corpus.

Everything else is parked away from a threshold on purpose: every duration sits inside the
0.5-20 s window, every level except the quiet one is -18 dBFS (clear of -30), and no tone
approaches full scale, so `duration_out_of_range` and `clipping` stay silent and the only flag the
reader meets is the one the corpus is teaching.

Every WAV is written at 16 kHz mono 16-bit directly — nothing here resamples — so the output is
plain numpy arithmetic, cross-machine stable, and safe for the exact byte comparison in
``tests/unit/test_example_data.py``. Run it from the repo root::

    python examples/generate.py
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `examples/` reusing `tests/` is an odd-looking arrow, but both are dev-time-only trees and
    # the alternative — a second tone generator — would make ADR-0008's "single source of fixture
    # truth" quietly false. The bootstrap lets `python examples/generate.py` find it from the
    # repo root, where sys.path[0] is `examples/` rather than the root.
    sys.path.insert(0, str(REPO_ROOT))

from tests import synth  # noqa: E402  (after the sys.path bootstrap above, by necessity)

DATA_IN = REPO_ROOT / "examples" / "data-in"

# The Normalized target (ADR-0005), written directly so the generator never resamples.
SAMPLE_RATE = 16000
BIT_DEPTH = 16
CHANNELS = 1

# The clean level, comfortably clear of the -30 dBFS `low_volume` knob, and the one quiet take
# that sits below it. Durations pair with frequencies that make `freq_hz * duration_s` whole, so
# each tone is an integer number of cycles and its RMS is exact to rounding (see `synth._tone`).
CLEAN_DBFS = -18.0
QUIET_DBFS = -36.0


@dataclass(frozen=True)
class _ExampleRecording:
    """One example Recording: the WAV to synthesize plus its ``recordings.csv`` row."""

    path: str
    freq_hz: float
    duration_s: float
    amp_dbfs: float
    speaker_id: str
    session_id: str
    prompt_text: str
    device: str
    environment: str

    def csv_row(self) -> dict[str, str]:
        return {
            "path": self.path,
            "speaker_id": self.speaker_id,
            "session_id": self.session_id,
            "prompt_text": self.prompt_text,
            "device": self.device,
            "environment": self.environment,
        }


# Named so a reader scanning `examples/data-in/` sees the corpus structure in the filenames alone.
RECORDINGS = [
    # --- Speaker a, Session a1 ----------------------------------------------------------------
    _ExampleRecording(
        path="spk_a/sess_a1/a1_01.wav",
        freq_hz=220.0,
        duration_s=1.5,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a1",
        prompt_text="The quick brown fox jumps over the lazy dog.",
        device="usb condenser microphone",
        environment="quiet room",
    ),
    _ExampleRecording(
        path="spk_a/sess_a1/a1_02.wav",
        freq_hz=330.0,
        duration_s=2.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a1",
        prompt_text="She sells sea shells by the sea shore.",
        device="usb condenser microphone",
        environment="quiet room",
    ),
    _ExampleRecording(
        path="spk_a/sess_a1/a1_03.wav",
        freq_hz=440.0,
        duration_s=1.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a1",
        prompt_text="A stitch in time saves nine.",
        device="usb condenser microphone",
        environment="quiet room",
    ),
    # --- Speaker a, Session a2: the second take of one Prompt lives here ----------------------
    _ExampleRecording(
        path="spk_a/sess_a2/a2_01.wav",
        freq_hz=220.0,
        duration_s=2.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a2",
        prompt_text="Please read the sentence on the card in front of you.",
        device="usb condenser microphone",
        environment="home office",
    ),
    # The retake: same Speaker, same Session, same Prompt as `a2_01`, a different signal. Both
    # attempts are data — neither is a keeper the other loses to. Every Recording's bytes are
    # decided entirely by its `(freq_hz, duration_s, amp_dbfs)` triple, so those triples must stay
    # distinct corpus-wide: two Recordings sharing one would be byte-identical Originals and
    # collapse to a single Recording at ingest (ADR-0001), silently shrinking the corpus.
    _ExampleRecording(
        path="spk_a/sess_a2/a2_02.wav",
        freq_hz=550.0,
        duration_s=1.5,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a2",
        prompt_text="Please read the sentence on the card in front of you.",
        device="usb condenser microphone",
        environment="home office",
    ),
    _ExampleRecording(
        path="spk_a/sess_a2/a2_03.wav",
        freq_hz=330.0,
        duration_s=1.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_a",
        session_id="sess_a2",
        prompt_text="How much wood would a woodchuck chuck.",
        device="usb condenser microphone",
        environment="home office",
    ),
    # --- Speaker b, Session b1: the quiet take lives here --------------------------------------
    _ExampleRecording(
        path="spk_b/sess_b1/b1_01.wav",
        freq_hz=440.0,
        duration_s=1.5,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_b",
        session_id="sess_b1",
        prompt_text="The rain in Spain falls mainly on the plain.",
        device="laptop built-in microphone",
        environment="living room",
    ),
    # The one Recording below the -30 dBFS knob: it trips `low_volume` and stays in the Manifest.
    _ExampleRecording(
        path="spk_b/sess_b1/b1_02.wav",
        freq_hz=330.0,
        duration_s=2.0,
        amp_dbfs=QUIET_DBFS,
        speaker_id="spk_b",
        session_id="sess_b1",
        prompt_text="I moved too far from the microphone on this one.",
        device="laptop built-in microphone",
        environment="living room",
    ),
    _ExampleRecording(
        path="spk_b/sess_b1/b1_03.wav",
        freq_hz=220.0,
        duration_s=1.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_b",
        session_id="sess_b1",
        prompt_text="Every good boy deserves fudge.",
        device="laptop built-in microphone",
        environment="living room",
    ),
    # --- Speaker b, Session b2 -----------------------------------------------------------------
    _ExampleRecording(
        path="spk_b/sess_b2/b2_01.wav",
        freq_hz=330.0,
        duration_s=1.5,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_b",
        session_id="sess_b2",
        prompt_text="Pack my box with five dozen liquor jugs.",
        device="field recorder",
        environment="parked car",
    ),
    _ExampleRecording(
        path="spk_b/sess_b2/b2_02.wav",
        freq_hz=440.0,
        duration_s=2.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_b",
        session_id="sess_b2",
        prompt_text="The five boxing wizards jump quickly.",
        device="field recorder",
        environment="parked car",
    ),
    _ExampleRecording(
        path="spk_b/sess_b2/b2_03.wav",
        freq_hz=550.0,
        duration_s=1.0,
        amp_dbfs=CLEAN_DBFS,
        speaker_id="spk_b",
        session_id="sess_b2",
        prompt_text="Bright vixens jump; dozy fowl quack.",
        device="field recorder",
        environment="parked car",
    ),
]


def write_example_tree(root: Path) -> None:
    """Write the example ``--data-in`` (``recordings.csv`` plus the twelve WAVs) into ``root``.

    Deterministic and resample-free, so the committed output is safe to byte-compare (ADR-0009).
    Subdirectories are created as needed: the corpus is laid out ``speaker/session/`` to show that
    ``--data-in`` may be arranged in any subdirectory layout the operator likes (#24).
    """
    root.mkdir(parents=True, exist_ok=True)
    for rec in RECORDINGS:
        wav = root / rec.path
        wav.parent.mkdir(parents=True, exist_ok=True)
        synth.write_wav(
            wav,
            freq_hz=rec.freq_hz,
            amp_dbfs=rec.amp_dbfs,
            duration_s=rec.duration_s,
            sample_rate=SAMPLE_RATE,
            bit_depth=BIT_DEPTH,
            channels=CHANNELS,
        )
    with (root / "recordings.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=synth.CSV_COLUMNS)
        writer.writeheader()
        for rec in RECORDINGS:
            writer.writerow(rec.csv_row())


def main() -> None:
    write_example_tree(DATA_IN)
    print(f"wrote {len(RECORDINGS)} recordings + recordings.csv to {DATA_IN}")


if __name__ == "__main__":
    main()
