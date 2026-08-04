"""The two Normalizers, and the properties the Metrics are allowed to assume (ADR-0018, #158).

Text Normalization is a function of text, so the whole tier is testable from one table of strings —
which is the point of it being symmetric. What is asserted here is what downstream scoring never
re-checks: the step order, the apostrophe/hyphen asymmetry, single-space output, and which tier can
empty a non-empty input.
"""

import csv
import inspect
from pathlib import Path

import pytest

from sdw.score.text_normalization import NORMALIZERS, TIER_A, TIER_B, tier_a, tier_b


class TestTierA:
    """ADR-0018's six steps, in order, addressed as `sdw-tier-a/1`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # ADR-0018's own worked table, verbatim.
            ("Bright vixens jump; dozy fowl quack.", "bright vixens jump dozy fowl quack"),
            ("It's Dr. Smith's well-known co-worker.", "its dr smiths well known co worker"),
            ("Mother-in-law's O'Brien recipe.", "mother in laws obrien recipe"),
            ("café naïve résumé", "cafe naive resume"),
            ("cafe naive resume", "cafe naive resume"),
            ("hello\tworld\xa0again\nnow", "hello world again now"),
            ("Um.", "um"),
        ],
    )
    def test_the_adr_table(self, text: str, expected: str) -> None:
        assert tier_a(text) == expected

    def test_nfkc_folds_compatibility_forms_step_1(self) -> None:
        # `ﬁ` is one codepoint until NFKC, and full-width forms are not ASCII until it either.
        assert tier_a("ﬁle") == "file"
        assert tier_a("ＦＵＬＬ") == "full"

    def test_casefold_not_lower_step_2(self) -> None:
        # Both assertions fail under `.lower()`, which is why the step names `.casefold()`:
        # `ß` stays itself rather than folding to `ss`, and Greek final sigma stays `ς` rather than
        # folding to `σ`, so the two spellings of the same word score as a substitution.
        assert tier_a("STRAßE") == "strasse"
        assert tier_a("οδος") == tier_a("οδοσ")

    def test_diacritics_are_stripped_step_3(self) -> None:
        # An orthographic equivalence, in the same class as case folding: the accented and
        # unaccented spellings must land on the same string or they score as substitutions.
        assert tier_a("Ångström") == tier_a("Angstrom")

    def test_apostrophes_are_deleted_and_hyphens_are_spaced(self) -> None:
        # The asymmetry is the decision (ADR-0018): an apostrophe is intra-word, a hyphen joins two
        # words. Spacing `don't` would inflate the Reference token count; spacing `well-known` buys
        # `well known` equivalence for free.
        assert tier_a("don't") == "dont"
        assert tier_a("well-known") == "well known"

    @pytest.mark.parametrize("apostrophe", ["'", "’", "ʼ", "′", "`"])
    def test_every_apostrophe_variant_is_deleted_not_spaced(self, apostrophe: str) -> None:
        # `ʼ` (U+02BC) is category `Lm`, a *letter* modifier, so step 5 would never touch it —
        # deleting the whole set at step 4 is what makes the variants interchangeable.
        assert tier_a(f"don{apostrophe}t") == "dont"

    def test_acute_accent_spaces_because_step_1_gets_to_it_first(self) -> None:
        # ADR-0018 lists `´` (U+00B4) in step 4's set, but step 1 runs first and NFKC decomposes it
        # to space + combining acute; step 3 then drops the mark and the space survives. Step order
        # is explicit in the ADR and load-bearing, so it wins — this asserts the consequence rather
        # than special-casing the character ahead of NFKC.
        assert tier_a("don´t") == "don t"

    @pytest.mark.parametrize("char", ["\t", "\n", "\r\n", "\xa0", " ", "   "])
    def test_every_whitespace_kind_collapses_to_one_space(self, char: str) -> None:
        # A contract obligation, not hygiene: a surviving tab makes a default tokenizer read
        # `hello\tworld` as a single token and report a 200% error rate (ADR-0018).
        assert tier_a(f"hello{char}world") == "hello world"

    def test_output_is_stripped(self) -> None:
        assert tier_a("  ...hello world!  ") == "hello world"

    def test_symbols_become_spaces_rather_than_vanishing(self) -> None:
        # Step 5 spaces `M*`/`S*`/`P*` — joining rather than spacing would silently merge tokens.
        assert tier_a("50%+20%") == "50 20"

    def test_it_cannot_empty_a_non_empty_prompt(self) -> None:
        # The property that keeps empty normalized References an almost-exclusively Tier B
        # condition, which the edge-case rules depend on. It holds for anything carrying a letter
        # or digit: no step deletes those, and step 6 only collapses the separators around them.
        for prompt in _reference_prompts():
            assert tier_a(prompt) != ""
        assert tier_a("...5...") == "5"

    def test_it_is_idempotent(self) -> None:
        # Not a stated rule, but scoring normalizes text it may already have normalized, and a
        # second pass changing the string would make that silently unsafe.
        for prompt in _reference_prompts():
            assert tier_a(tier_a(prompt)) == tier_a(prompt)


class TestTierB:
    """OpenAI's normalizer, vendored verbatim, addressed as `whisper-english/b80bcf6`."""

    def test_it_can_empty_a_non_empty_input(self) -> None:
        # The condition Tier A cannot produce, and the reason an empty normalized Reference is
        # retained rather than dropped: dropping would score the two tiers over different Sample
        # sets and end the pairing that justifies computing both (ADR-0018).
        assert tier_b("Um.") == ""
        assert tier_a("Um.") == "um"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # The corruptions ADR-0018 accepted on the record. Asserted so that a silent upstream
            # re-vendor is a red test rather than a moved number: these are why Tier A is the
            # headline, and if they ever change, the identity string must change with them.
            ("O'Brien", "0 brien"),
            ("The dog's bone", "the dog is bone"),
            ("the rep", "the representative"),
        ],
    )
    def test_the_known_corruptions_are_still_present(self, text: str, expected: str) -> None:
        assert tier_b(text) == expected

    def test_output_is_single_spaced(self) -> None:
        assert tier_b("hello\tworld\xa0again\nnow") == "hello world again now"

    def test_the_vendored_tree_is_reachable_without_the_asr_extra(self) -> None:
        # Tier B is vendored rather than imported from `transformers` precisely so that Scoring
        # holds no dependency on the ASR stack (ADR-0023). Its data file must ship with it.
        from sdw.score._vendor.whisper_normalizers import english

        vendored = Path(english.__file__).parent
        assert (vendored / "english.json").is_file()
        # MIT attribution ships with the copy, not just with the checkout.
        assert "MIT License" in (vendored / "LICENSE").read_text(encoding="utf-8")


class TestSymmetry:
    """One function of text, applied identically to both sides — no role parameter anywhere."""

    @pytest.mark.parametrize("identity", [TIER_A, TIER_B])
    def test_a_normalizer_takes_text_and_nothing_else(self, identity: str) -> None:
        # Symmetry is structural or it is nothing: comparing two equal strings would pass under an
        # implementation carrying a `side=` default, so the signature is what gets asserted. A
        # Normalizer that could be told which side it was on would end the paired B−A delta.
        parameters = inspect.signature(NORMALIZERS[identity]).parameters
        assert [p.kind for p in parameters.values()] == [inspect.Parameter.POSITIONAL_OR_KEYWORD]
        (only,) = parameters.values()
        assert only.annotation is str
        assert only.default is inspect.Parameter.empty


class TestIdentityStrings:
    """Both tiers are addressable by the exact strings the Report prints (ADR-0022)."""

    def test_the_identity_strings_are_the_ones_the_report_names(self) -> None:
        assert TIER_A == "sdw-tier-a/1"
        assert TIER_B == "whisper-english/b80bcf6"

    def test_the_registry_holds_exactly_the_two_always_on_tiers(self) -> None:
        # Neither is selectable and there is no third: a registry that grew an entry would mean a
        # Report whose attribution no longer names every Normalizer that ran.
        assert set(NORMALIZERS) == {TIER_A, TIER_B}

    @pytest.mark.parametrize(("identity", "func"), [(TIER_A, tier_a), (TIER_B, tier_b)])
    def test_each_identity_addresses_its_own_tier(self, identity: str, func: object) -> None:
        assert NORMALIZERS[identity] is func

    def test_an_unversioned_identity_addresses_nothing(self) -> None:
        # The revision is part of the identity, so the bare name must not resolve (ADR-0018).
        with pytest.raises(KeyError):
            NORMALIZERS["whisper-english"]("hello")

    def test_the_registry_cannot_be_mutated_in_place(self) -> None:
        with pytest.raises(TypeError):
            NORMALIZERS["sdw-tier-a/2"] = tier_a  # type: ignore[index]


def _reference_prompts() -> list[str]:
    """The test reference tree's Prompts — real Reference text, not invented strings (ADR-0008)."""
    csv_path = Path(__file__).resolve().parents[1] / "fixtures" / "reference" / "recordings.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return [row["prompt_text"] for row in csv.DictReader(handle)]
