"""The one JSONL join every artifact writer goes through (#54).

These are the byte-format promises the Manifest, the HF view, and the quality report all inherit,
so they are asserted once here rather than re-asserted per writer. The point of the shared join is
that a writer cannot hold an opinion about any of them — each test below is a promise that would
otherwise have been re-derived, and silently re-baselined into one golden but not the other.
"""

from sdw.serialization import render_jsonl


class TestRenderJsonl:
    """The one JSONL join every artifact writer goes through (#54).

    These are the byte-format promises the Manifest and the quality report both inherit, so they
    are asserted once here rather than re-asserted per writer. The point of the shared join is
    that a writer cannot hold an opinion about any of them.
    """

    def test_separators_are_compact(self) -> None:
        text = render_jsonl([{"a": 1, "b": "x"}])
        assert text == '{"a":1,"b":"x"}\n'

    def test_non_ascii_is_emitted_as_utf_8_not_escaped(self) -> None:
        # The deliberate choice, and the one the two writers previously disagreed about: `text`
        # carries Prompt text verbatim, so escaping would make a non-Latin Manifest unreadable.
        assert render_jsonl([{"text": "Café ☕"}]) == '{"text":"Café ☕"}\n'

    def test_key_order_is_the_callers_not_sorted(self) -> None:
        # ADR-0006's Manifest order and ADR-0007's quality order are both non-alphabetical, so
        # `sort_keys` must stay off here even though the config's own preimage sorts.
        assert render_jsonl([{"b": 1, "a": 2}]) == '{"b":1,"a":2}\n'

    def test_every_line_is_lf_terminated(self) -> None:
        text = render_jsonl([{"a": 1}, {"a": 2}])
        assert text == '{"a":1}\n{"a":2}\n'
        assert "\r" not in text

    def test_nothing_renders_an_empty_file_not_a_lone_newline(self) -> None:
        assert render_jsonl([]) == ""
