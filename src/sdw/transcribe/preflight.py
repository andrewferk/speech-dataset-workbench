"""Everything structural, checked before anything expensive happens (#164, ADR-0017).

Two properties, and each is a decision rather than a style. **It runs before the model loads**, so
nothing structural can abort after minute zero and "abort on structural failure" never costs forty
minutes. And **it reports everything wrong at once** rather than aborting on first contact, so the
operator fixes one round of problems rather than several — #8's reason for `validate`, discharged
inside the command where it cannot be skipped.
"""

from collections.abc import Sequence
from pathlib import Path

from sdw.errors import HardError
from sdw.transcribe import audio, dataset
from sdw.transcribe.dataset import DatasetVersion, Descriptor, Sample


def preflight(*, root: Path, run_dir: Path) -> DatasetVersion:
    """Read the Dataset Version, decode every Sample's audio, and check the Run's name is free.

    Returns what it read, so the Run does not parse the dataset a second time. Raises
    :class:`HardError` listing every problem found — the audio pass alone can name several, and a
    missing WAV halfway through the corpus is exactly the failure that must not surface late.
    """
    problems: list[str] = []
    descriptor: Descriptor | None = None
    samples: tuple[Sample, ...] | None = None

    try:
        descriptor = dataset.read_descriptor(root)
    except HardError as error:
        problems.append(str(error))
    try:
        samples = dataset.read_samples(root)
    except HardError as error:
        problems.append(str(error))

    if samples is not None:
        if not samples:
            problems.append(f"the Dataset Version holds zero Samples: {root}")
        problems.extend(_undecodable(root, samples))

    if run_dir.exists():
        # A `-2` suffix would produce two directories whose names imply an ordering relationship
        # they do not have; two Runs in one UTC second means two concurrent invocations of a
        # multi-minute stage on a single-operator tool (ADR-0021).
        problems.append(f"the Run directory already exists: {run_dir}")

    if problems or descriptor is None or samples is None:
        raise HardError(_message(problems))
    return DatasetVersion(root=root, descriptor=descriptor, samples=samples)


def _undecodable(root: Path, samples: Sequence[Sample]) -> list[str]:
    """Every Sample whose Normalized audio is missing or will not decode (ADR-0017).

    Every Sample, not the first failure: the audio is the one input the operator is most likely to
    have moved, and naming three missing files at once costs the same seconds as naming one.
    """
    problems = []
    for sample in samples:
        try:
            audio.read(root / sample.audio_filepath)
        except HardError as error:
            problems.append(str(error))
    return problems


def _message(problems: Sequence[str]) -> str:
    """The whole preflight as one error: a count, then one line per problem."""
    count = f"{len(problems)} problem{'' if len(problems) == 1 else 's'}"
    return "\n".join([f"transcribe preflight found {count}:", *(f"  - {p}" for p in problems)])
