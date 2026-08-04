"""The two Normalizers every Metric is computed under, addressed by identity string (ADR-0018).

Both always run and neither is selectable. Each is a function of *text*, never of role — a `side=`
parameter here would end the pairing that makes the Tier B − Tier A delta exact.
"""

import unicodedata
from collections.abc import Callable, Mapping
from functools import cache
from types import MappingProxyType

from sdw.score._vendor.whisper_normalizers.english import EnglishTextNormalizer

# The revision in TIER_B is part of the identity, not a footnote (ADR-0018). Both strings appear in
# every Evaluation Report's attribution (ADR-0022).
TIER_A = "sdw-tier-a/1"
TIER_B = "whisper-english/b80bcf6"

# Step 4 — deleted rather than spaced, which is what keeps `dont` one token (ADR-0018). `´` (U+00B4)
# is in the ADR's set but never reaches this step: NFKC decomposes it to space + combining acute, so
# it spaces. Step order is explicit in the ADR — don't repair that by moving step 4 up.
_APOSTROPHES = frozenset("'’ʼ′`´")

# Step 5 — the top-level Unicode categories that become a space.
_SPACED_CATEGORIES = frozenset("MSP")


def tier_a(text: str) -> str:
    """Tier A (`sdw-tier-a/1`): ADR-0018's six steps, in order.

    Returns single-space-separated, stripped text — a contract obligation, since a surviving tab
    scores 200% under a default tokenizer.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = "".join(c for c in text if c not in _APOSTROPHES)
    text = "".join(" " if unicodedata.category(c)[0] in _SPACED_CATEGORIES else c for c in text)
    # `split()` also covers the whitespace step 5 leaves alone — tabs and newlines are `Cc`.
    return " ".join(text.split())


@cache
def _english_text_normalizer() -> EnglishTextNormalizer:
    """Built once — construction reads the 56 KB `english.json` spelling map off disk."""
    return EnglishTextNormalizer()


def tier_b(text: str) -> str:
    """Tier B (`whisper-english/b80bcf6`): the vendored normalizer, called unmodified.

    Unlike Tier A it can return `""` for non-empty input, and it carries the corruptions ADR-0018
    accepted on the record.
    """
    return str(_english_text_normalizer()(text))


NORMALIZERS: Mapping[str, Callable[[str], str]] = MappingProxyType({TIER_A: tier_a, TIER_B: tier_b})
