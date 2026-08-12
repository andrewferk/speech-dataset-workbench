"""The pinned checkpoint's constants and the shape of what it reports (#166, ADR-0016).

Two kinds of assertion, and the split is the point. **The constants are read from the source by
AST**, so the pinning survives in the torch-free `check` job — which is where it has to survive,
because the file that holds them is the one file that job can never import. **The rest imports the
leaf**, and therefore runs only in the `asr` job, where the operator's own venv shape is the one
under test (ADR-0025).

No test here performs a decode or resolves a weight. What can be checked without one is exactly what
is checked: that the repo id and revision are literals with no override, that the seven decode
constants are the seven, that no rejected API surface appears anywhere in the module, and that
`run.json`'s three backend blocks come out shaped the way ADR-0020 reads them.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

import pytest

import sdw

LEAF = Path(sdw.__file__).parent / "transcribe" / "whisper.py"
TREE = ast.parse(LEAF.read_text(encoding="utf-8"))


def _without_prose(tree: ast.Module) -> ast.Module:
    """The module with every docstring dropped; `ast.unparse` drops the comments for free.

    The several *absence* claims below are claims about code, and a file that documents why it does
    not reach for MPS necessarily contains the string `mps`. Scanning the raw text would make the
    honest comment the failure, which is precisely the wrong incentive to build into a guardrail.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]
    return tree


def _names(tree: ast.AST) -> set[str]:
    """Every identifier and string literal the code uses, prose excluded.

    Names rather than a substring scan, because `return_timestamps` contains `mps` and a guardrail
    that cannot tell those apart is a guardrail that gets deleted the first time it is wrong.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Name():
                names.add(node.id)
            case ast.Attribute():
                names.add(node.attr)
            case ast.keyword() if node.arg:
                names.add(node.arg)
            case ast.arg():
                names.add(node.arg)
            case ast.alias():
                names.update(node.name.split("."))
            case ast.ImportFrom() if node.module:
                names.update(node.module.split("."))
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.Constant() if isinstance(node.value, str):
                names.add(node.value)
    return {name.lower() for name in names}


CODE_TREE = _without_prose(ast.parse(LEAF.read_text(encoding="utf-8")))
NAMES = _names(CODE_TREE)

# ADR-0016's table, restated here as the second copy that makes a silent edit loud. This is the one
# place duplication is the mechanism rather than a smell: a constant asserted against itself would
# assert nothing.
REPO_ID = "openai/whisper-large-v3-turbo"
REVISION = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"

DECODE = {
    "task": "transcribe",
    "do_sample": False,
    "num_beams": 1,
    "temperature": None,
    "condition_on_prev_tokens": False,
    "return_timestamps": False,
}

requires_the_extra = pytest.mark.skipif(
    importlib.util.find_spec("transformers") is None,
    reason="the asr extra is not installed; the `asr` CI job runs these (ADR-0025)",
)


def _constant(name: str) -> Any:
    """One module-level assignment of ``name``, evaluated as a literal.

    Literal, not imported: a value this cannot evaluate is a value that stopped being a constant,
    which is the change these tests exist to notice.
    """
    for node in TREE.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        if name in targets and node.value is not None:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a module-level constant of {LEAF.name}")


def _generate_call() -> ast.Call:
    """The module's one `generate()` call — one call site, so one decode to describe."""
    (call,) = [
        node
        for node in ast.walk(CODE_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "generate"
    ]
    return call


def _generate_keywords() -> set[str | None]:
    """Every keyword that call names; ``None`` is the `**DECODE` unpacking."""
    return {keyword.arg for keyword in _generate_call().keywords}


class TestPinning:
    """The checkpoint is named by the repository, not by the operator (ADR-0016)."""

    def test_the_repo_id_and_revision_are_source_constants(self) -> None:
        assert _constant("REPO_ID") == REPO_ID
        # A sha, never a tag or a branch: those could name different bytes online than the ones
        # already cached, and the offline Run would be the one telling the truth.
        assert _constant("REVISION") == REVISION
        assert len(REVISION) == 40

    def test_nothing_can_override_the_checkpoint(self) -> None:
        # Not configuration, not a CLI argument, not an environment variable, not a registry entry.
        # `add_argument` and `environ` would each be a different back door to the same widening,
        # which ADR-0016 made an ADR change rather than a code change.
        for back_door in ("environ", "getenv", "add_argument", "argparse", "tomllib"):
            assert back_door not in NAMES
        # `sdw.config` is the fifth back door and cannot be checked by name — `config` is also the
        # loaded checkpoint's own attribute — so it is checked as an import.
        assert "sdw.config" not in {
            node.module for node in ast.walk(CODE_TREE) if isinstance(node, ast.ImportFrom)
        }

    def test_the_device_and_dtype_are_cpu_and_float32(self) -> None:
        assert _constant("DEVICE") == "cpu"
        assert _constant("DTYPE_NAME") == "float32"

    def test_no_accelerator_path_exists(self) -> None:
        # Not "MPS is not the default" — no path exists at all. torch's randomness notes mention MPS
        # zero times, and a v0.3 comparison straddling two devices would not mean what it appears to
        # (ADR-0016).
        for accelerator in ("mps", "cuda", "is_available", "device_count", "float16", "bfloat16"):
            assert accelerator not in NAMES


class TestDecodeConstants:
    """Seven constants, no guards — and the guards' absence is the assertion (ADR-0016)."""

    def test_the_six_run_wide_constants_are_exactly_these(self) -> None:
        # Exactly, not a superset: an eighth parameter appearing here is a decode this repo no
        # longer describes, and `run.json` renders this mapping verbatim.
        assert _constant("DECODE") == DECODE

    def test_the_seventh_constant_is_the_effective_language(self) -> None:
        # `language` is absent from the mapping above because it is resolved per Run from the
        # Manifest and recorded in its own `run.json` block — a fact recorded twice can disagree
        # with itself (ADR-0020).
        assert "language" not in DECODE
        (language,) = [
            keyword for keyword in _generate_call().keywords if keyword.arg == "language"
        ]
        # The resolved `Language`'s value, so `run.json`'s language block and the decode cannot
        # disagree about what the model was told.
        assert ast.unparse(language.value) == "language.value"

    def test_generate_is_passed_the_constants_and_nothing_else(self) -> None:
        # Read off the call rather than off the text: `max_length` is a *padding* strategy for the
        # feature extractor and a length cap for `generate`, and only one of the two is forbidden.
        assert _generate_keywords() == {"attention_mask", "language", None}

    @pytest.mark.parametrize(
        "guard", ["repetition_penalty", "no_repeat_ngram_size", "max_new_tokens", "max_length"]
    )
    def test_no_output_guard_is_applied(self, guard: str) -> None:
        # A runaway decode must surface as a Metric above 1.0 rather than be tidied away at
        # generation time; Whisper's 448 decoder positions already bound it (ADR-0016).
        assert guard not in _generate_keywords()
        assert guard not in DECODE

    def test_no_language_detection_path_exists(self) -> None:
        # Detection would make the Hypothesis depend on a per-Sample input appearing nowhere in the
        # provenance, and mis-detection on quiet audio is indistinguishable from recognition error
        # (ADR-0016).
        for detection in ("detect_language", "auto", "language_detection"):
            assert detection not in NAMES


class TestApiSurface:
    """The explicit processor and `generate()`, and no way to hand the model a path (ADR-0016)."""

    def test_the_pipeline_helper_appears_nowhere(self) -> None:
        # Every path-based entry point routes through FFmpeg, and the HF pipeline calls
        # `ffmpeg_read` for `str`/`bytes` input — which would undo ADR-0005 at the API level.
        assert "pipeline" not in NAMES
        assert "automatic-speech-recognition" not in NAMES

    def test_the_model_is_handed_an_array_and_never_a_path(self) -> None:
        # `Path` is imported, for the model card — so the claim has to be about the *decode* rather
        # than about the file: `transcribe` takes an array, and names no path type at all.
        (transcribe,) = [
            node
            for node in ast.walk(TREE)
            if isinstance(node, ast.FunctionDef) and node.name == "transcribe"
        ]
        arguments = [argument.arg for argument in transcribe.args.args]
        assert arguments == ["self", "waveform", "language"]
        assert "Path" not in ast.unparse(transcribe)

    def test_the_explicit_classes_are_the_ones_imported(self) -> None:
        imported = {
            alias.name
            for node in ast.walk(TREE)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("transformers")
            for alias in node.names
        }
        assert {"WhisperProcessor", "WhisperForConditionalGeneration"} <= imported


class TestModelCard:
    """The licence is read from the fetched artifact, never from a constant here (ADR-0016)."""

    @requires_the_extra
    @pytest.mark.parametrize(
        ("card", "expected"),
        [
            ("---\nlicense: mit\nlanguage:\n- en\n---\n\n# Card\n", "mit"),
            ('---\nlicense: "apache-2.0"\n---\n', "apache-2.0"),
            ("---\nlanguage:\n- en\n---\n", None),
            ("# Card with no front matter\n", None),
            ("", None),
            # The `license` key of the *body* is not front matter, and reading it would report a
            # licence the card never declared.
            ("---\nlanguage: en\n---\nlicense: gpl-3.0\n", None),
        ],
        ids=["plain", "quoted", "absent", "no-front-matter", "empty", "below-the-fence"],
    )
    def test_the_declared_licence_is_read_off_the_front_matter(
        self, card: str, expected: str | None
    ) -> None:
        from sdw.transcribe import whisper

        assert whisper._declared_license(card) == expected

    def test_no_licence_string_is_hard_coded(self) -> None:
        # A hard-coded licence is a lie waiting for the next checkpoint: turbo makes the README/card
        # conflict vanish today, and only today (ADR-0016). Checked over string *literals* rather
        # than over the text, so prose about licensing does not fail it and a constant does.
        literals = {
            node.value.lower()
            for node in ast.walk(TREE)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert not literals & {"mit", "apache-2.0", "cc-by-4.0", "cc-by-nc-4.0", "bsd-3-clause"}


class TestProvenance:
    """The three blocks `run.json` renders verbatim, assembled without loading a checkpoint."""

    @requires_the_extra
    def test_the_blocks_carry_every_field_the_adr_mandates(self) -> None:
        import torch
        import transformers

        from sdw.transcribe import whisper

        provenance = whisper._provenance(license="the-licence", attn_implementation="the-kernel")

        assert provenance.model == {
            "repo_id": REPO_ID,
            "revision": REVISION,
            "license": "the-licence",
        }
        assert provenance.decode == DECODE
        assert provenance.runtime == {
            "name": "transformers",
            "transformers_version": transformers.__version__,
            "torch_version": torch.__version__,
            "device": "cpu",
            "dtype": "float32",
            # Recorded, not pinned: each is a numerics input with no correct value (ADR-0016).
            "attn_implementation": "the-kernel",
            "torch_num_threads": torch.get_num_threads(),
        }

    @requires_the_extra
    def test_an_undeclared_licence_is_recorded_as_null_rather_than_guessed(self) -> None:
        from sdw.transcribe import whisper

        provenance = whisper._provenance(license=None, attn_implementation="the-kernel")
        assert provenance.model["license"] is None

    @requires_the_extra
    def test_the_recorded_decode_is_the_mapping_the_call_site_unpacks(self) -> None:
        # One mapping feeds both `generate()` and `run.json`, so the Run's provenance cannot
        # describe a decode the call did not perform (ADR-0016).
        from sdw.transcribe import whisper

        provenance = whisper._provenance(license=None, attn_implementation="the-kernel")
        assert provenance.decode == dict(whisper.DECODE)
        # The unpacking is what makes them one mapping rather than two that happen to agree.
        (unpacked,) = [
            keyword.value for keyword in _generate_call().keywords if keyword.arg is None
        ]
        assert ast.unparse(unpacked) == "DECODE"
