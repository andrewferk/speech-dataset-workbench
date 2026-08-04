"""`sdw transcribe`'s internals: preflight, the decode loop, and the sentinel (#164, ADR-0017).

The Run directory is created at its **final name** and written into. There is no staging and no
rename-on-success: ADR-0003's protocol is indivisible, and its stale-`.tmp` sweep would delete the
very minutes incremental writing exists to save (ADR-0021). `run.json` written last is the sole
completeness mechanism, and a crashed Run is kept forever — it *is* the model output.
"""

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt

from sdw.errors import HardError
from sdw.transcribe import audio, provenance, record
from sdw.transcribe.backend import Backend, Language, resolve_language
from sdw.transcribe.dataset import ENCODING, Sample
from sdw.transcribe.preflight import preflight


def transcribe(*, dataset: Path, eval_out: Path) -> None:
    """The CLI's entry: hand :func:`run` the thunk that loads the pinned model.

    The import of the ASR extra lives inside that thunk, which is what keeps every other module
    under `sdw.transcribe` importable with no extra installed (ADR-0023, ADR-0025). #166 fills this
    in; until it does the command parses and refuses, rather than inventing a Hypothesis.
    """
    raise HardError(
        "sdw transcribe has no ASR backend yet — the pinned model lands with #166 (ADR-0016). "
        "Everything else in the command is built: preflight, Hypothesis Record, and run.json."
    )


def run(*, dataset: Path, eval_out: Path, load_backend: Callable[[], Backend]) -> Path:
    """Transcribe the entire Dataset Version into one new Run directory, and return its path.

    The whole Dataset Version, always: narrowing at Transcription is lossy where narrowing at
    Scoring is free, so the expensive stage never makes that choice (ADR-0017). `load_backend` is
    the test seam — a parameter on an internal function, unreachable from the CLI (ADR-0025).
    """
    started = datetime.now(UTC)
    run_dir = eval_out / provenance.run_directory_name(started)
    version = preflight(root=dataset, run_dir=run_dir)
    # A thunk, not a Backend: the preflight has to finish before the checkpoint is loaded, or a
    # dataset knowably broken in seconds costs the operator the model load first (ADR-0017).
    backend = load_backend()
    language = resolve_language(version.descriptor.lang)

    run_dir.mkdir(parents=True)
    long_form_count = 0
    with record.RecordWriter(run_dir / record.RECORD_NAME) as writer:
        for sample in version.samples:
            waveform = audio.read(version.audio_path(sample))
            long_form = audio.is_long_form(waveform)
            long_form_count += int(long_form)
            writer.append(_transcribed(sample, waveform, language, backend, long_form=long_form))

    # Last, and only now: the sentinel's presence is what tells `score` the Record is complete.
    (run_dir / provenance.RUN_DESCRIPTOR_NAME).write_text(
        provenance.render(
            descriptor=version.descriptor,
            backend=backend.provenance,
            language=language,
            record_line_count=writer.line_count,
            timing=provenance.Timing(
                started_at=provenance.timestamp(started),
                finished_at=provenance.timestamp(datetime.now(UTC)),
            ),
        ),
        encoding=ENCODING,
    )

    _report(run_dir, long_form_count)
    return run_dir


def _transcribed(
    sample: Sample,
    waveform: npt.NDArray[np.float32],
    language: Language,
    backend: Backend,
    *,
    long_form: bool,
) -> record.Hypothesis:
    """One Sample transcribed, or recorded as failed — a per-Sample failure never aborts the Run.

    The exception's detail reaches stderr and nowhere else: free text in `error` would put absolute
    paths into a durable artifact (ADR-0017, ADR-0019).
    """
    try:
        hypothesis = backend.transcribe(waveform, language)
    except Exception as error:
        print(f"warning: transcription failed for {sample.id}: {error}", file=sys.stderr)
        return record.failed(sample, long_form=long_form)
    return record.transcribed(sample, hypothesis=hypothesis, long_form=long_form)


def _report(run_dir: Path, long_form_count: int) -> None:
    """The Run's path on stdout, and the long-form count on stderr when it is non-zero.

    The count is disclosed at Run level and never a rejection: refusing the dataset's own data over
    an internal detail of Whisper's window size would stop being a stranger-consumer and start
    imposing an architecture on the dataset (ADR-0016).
    """
    if long_form_count:
        print(
            f"warning: {long_form_count} Sample(s) decoded in the long-form regime "
            f"(over {audio.LONG_FORM_FRAMES} frames)",
            file=sys.stderr,
        )
    print(run_dir)
