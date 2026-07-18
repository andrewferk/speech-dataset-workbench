"""``recordings.csv`` parsing, path resolution, and content identity (#24).

The stage is a pure function of the ``--data-in`` tree: it reads the fixed-name CSV, resolves each
declared path, derives content-derived ids (ADR-0001), and collapses byte-identical Originals — or
aborts with a :class:`HardError` on any structural problem (ADR-0002/0003). These tests pin the
identity formulas exactly, the abort surface for each malformation, and the one decision the ticket
had to make: byte-identical Originals with conflicting metadata abort (ADR-0013).
"""

import hashlib
import unicodedata
from pathlib import Path

import pytest

from sdw.errors import HardError
from sdw.ingest import Recording, read_recordings
from tests import synth

HEADER = "path,speaker_id,session_id,prompt_text,device,environment"


def _write_csv(data_in: Path, *rows: str) -> None:
    data_in.mkdir(parents=True, exist_ok=True)
    body = "\n".join([HEADER, *rows]) + "\n"
    (data_in / "recordings.csv").write_text(body, newline="", encoding="utf-8")


def _write_original(data_in: Path, rel: str, content: bytes = b"original-bytes") -> None:
    path = data_in / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _one(recordings: list[Recording]) -> Recording:
    assert len(recordings) == 1
    return recordings[0]


class TestHappyPath:
    def test_derives_a_recording_per_row(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"aaa")
        _write_original(data_in, "sub/b.wav", b"bbb")
        _write_csv(
            data_in,
            "a.wav,spk_a,sess_1,Hello there.,mic,quiet room",
            "sub/b.wav,spk_b,sess_2,Goodbye.,recorder,office",
        )
        recordings = read_recordings(data_in)
        assert {r.path for r in recordings} == {"a.wav", "sub/b.wav"}
        assert {r.speaker_id for r in recordings} == {"spk_a", "spk_b"}

    def test_carries_metadata_verbatim(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav")
        _write_csv(data_in, "a.wav,spk_a,2026-07-14,Read this aloud.,USB mic,quiet room")
        rec = _one(read_recordings(data_in))
        assert rec.speaker_id == "spk_a"
        assert rec.session_id == "2026-07-14"
        assert rec.prompt_text == "Read this aloud."
        assert rec.device == "USB mic"
        assert rec.environment == "quiet room"

    def test_the_reference_tree_ingests_cleanly(self, tmp_path: Path) -> None:
        # The committed reference --data-in (four distinct Recordings across two Speakers) is the
        # canonical valid input; it must parse without abort and yield four Recordings.
        data_in = tmp_path / "reference"
        synth.write_reference_tree(data_in)
        recordings = read_recordings(data_in)
        assert len(recordings) == 4
        assert len({r.recording_id for r in recordings}) == 4


class TestContentIdentity:
    def test_recording_id_and_content_hash_are_the_sha256_of_bytes(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        content = b"the exact captured bytes"
        _write_original(data_in, "a.wav", content)
        _write_csv(data_in, "a.wav,spk,s,Hi.,mic,room")
        rec = _one(read_recordings(data_in))
        digest = hashlib.sha256(content).hexdigest()
        assert rec.recording_id == f"rec_{digest[:16]}"
        assert rec.content_hash == f"sha256:{digest}"
        assert len(rec.recording_id) == len("rec_") + 16
        short = rec.recording_id.removeprefix("rec_")
        assert short == rec.content_hash.removeprefix("sha256:")[:16]

    def test_prompt_id_hashes_normalized_text(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav")
        _write_csv(data_in, "a.wav,spk,s,Hello world.,mic,room")
        rec = _one(read_recordings(data_in))
        expected = hashlib.sha256(b"Hello world.").hexdigest()
        assert rec.prompt_id == f"prm_{expected[:16]}"

    def test_prompt_normalization_trims_and_collapses_whitespace(self, tmp_path: Path) -> None:
        # NFC + trim + whitespace-collapse: leading/trailing/internal-run whitespace is normalized
        # away, so these two prompt texts are the same Prompt (ADR-0001).
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"a")
        _write_original(data_in, "b.wav", b"b")
        _write_csv(
            data_in,
            'a.wav,spk,s1,"  Hello   world. ",mic,room',
            'b.wav,spk,s2,"Hello world.",mic,room',
        )
        a, b = sorted(read_recordings(data_in), key=lambda r: r.path)
        assert a.prompt_id == b.prompt_id

    def test_no_case_or_punctuation_folding(self, tmp_path: Path) -> None:
        # "Hello." and "hello" must stay distinct Prompts — normalization is whitespace-only.
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"a")
        _write_original(data_in, "b.wav", b"b")
        _write_csv(
            data_in,
            "a.wav,spk,s1,Hello.,mic,room",
            "b.wav,spk,s2,hello,mic,room",
        )
        a, b = sorted(read_recordings(data_in), key=lambda r: r.path)
        assert a.prompt_id != b.prompt_id

    def test_prompt_id_is_nfc_normalized(self, tmp_path: Path) -> None:
        # A decomposed (NFD) and composed (NFC) spelling of the same text are one Prompt.
        composed = unicodedata.normalize("NFC", "café")
        decomposed = unicodedata.normalize("NFD", "café")
        assert composed != decomposed  # different code points, same text
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"a")
        _write_original(data_in, "b.wav", b"b")
        _write_csv(
            data_in,
            f"a.wav,spk,s1,{composed},mic,room",
            f"b.wav,spk,s2,{decomposed},mic,room",
        )
        a, b = sorted(read_recordings(data_in), key=lambda r: r.path)
        assert a.prompt_id == b.prompt_id


class TestDeduplication:
    def test_byte_identical_originals_with_agreeing_metadata_collapse(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"same-bytes")
        _write_original(data_in, "copy.wav", b"same-bytes")
        _write_csv(
            data_in,
            "a.wav,spk,s,Hi.,mic,room",
            "copy.wav,spk,s,Hi.,mic,room",
        )
        # One Recording, even though it was listed under two paths (ADR-0001).
        rec = _one(read_recordings(data_in))
        assert rec.path == "a.wav"  # first occurrence wins

    def test_conflicting_metadata_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"same-bytes")
        _write_original(data_in, "b.wav", b"same-bytes")
        _write_csv(
            data_in,
            "a.wav,spk,session_one,Hi.,mic,room",
            "b.wav,spk,session_two,Hi.,mic,room",
        )
        with pytest.raises(HardError) as exc:
            read_recordings(data_in)
        # ADR-0013: the abort names both paths, the shared recording_id, and the disagreeing field,
        # so the operator can find the conflict.
        message = str(exc.value)
        assert "session_id" in message
        assert "a.wav" in message and "b.wav" in message
        recording_id = f"rec_{hashlib.sha256(b'same-bytes').hexdigest()[:16]}"
        assert recording_id in message

    @pytest.mark.parametrize(
        ("field", "row_a", "row_b"),
        [
            ("speaker_id", "spk_a,s,Hi.,mic,room", "spk_b,s,Hi.,mic,room"),
            ("prompt_text", "spk,s,Hello.,mic,room", "spk,s,Goodbye.,mic,room"),
            ("device", "spk,s,Hi.,mic_one,room", "spk,s,Hi.,mic_two,room"),
            ("environment", "spk,s,Hi.,mic,quiet", "spk,s,Hi.,mic,loud"),
        ],
    )
    def test_any_agreement_field_conflict_aborts(
        self, tmp_path: Path, field: str, row_a: str, row_b: str
    ) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"same-bytes")
        _write_original(data_in, "b.wav", b"same-bytes")
        _write_csv(data_in, f"a.wav,{row_a}", f"b.wav,{row_b}")
        with pytest.raises(HardError, match=field):
            read_recordings(data_in)

    def test_distinct_bytes_never_collapse(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav", b"aaa")
        _write_original(data_in, "b.wav", b"bbb")
        _write_csv(
            data_in,
            "a.wav,spk,s,Hi.,mic,room",
            "b.wav,spk,s,Hi.,mic,room",
        )
        assert len(read_recordings(data_in)) == 2


class TestUnlistedFilesIgnored:
    def test_files_absent_from_the_csv_are_silently_ignored(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "listed.wav", b"a")
        _write_original(data_in, "stray.wav", b"b")  # present on disk, absent from the CSV
        _write_original(data_in, "notes/scratch.txt", b"c")
        _write_csv(data_in, "listed.wav,spk,s,Hi.,mic,room")
        rec = _one(read_recordings(data_in))
        assert rec.path == "listed.wav"


class TestStructuralAborts:
    def test_missing_recordings_csv_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        with pytest.raises(HardError, match="recordings.csv"):
            read_recordings(data_in)

    def test_header_only_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in)  # header, no rows
        with pytest.raises(HardError, match="no rows"):
            read_recordings(data_in)

    def test_empty_file_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text("", encoding="utf-8")
        with pytest.raises(HardError):
            read_recordings(data_in)

    def test_missing_column_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text(
            "path,speaker_id,session_id,prompt_text,device\na.wav,spk,s,Hi.,mic\n",
            encoding="utf-8",
        )
        _write_original(data_in, "a.wav")
        with pytest.raises(HardError, match="environment"):
            read_recordings(data_in)

    def test_unexpected_column_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text(
            HEADER + ",extra\na.wav,spk,s,Hi.,mic,room,junk\n",
            encoding="utf-8",
        )
        _write_original(data_in, "a.wav")
        with pytest.raises(HardError, match="extra"):
            read_recordings(data_in)

    def test_column_order_is_free(self, tmp_path: Path) -> None:
        # RFC-4180 does not fix column order; a reordered header with the right set is valid.
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text(
            "speaker_id,path,environment,device,prompt_text,session_id\n"
            "spk_a,a.wav,room,mic,Hi.,s1\n",
            encoding="utf-8",
        )
        _write_original(data_in, "a.wav")
        rec = _one(read_recordings(data_in))
        assert rec.speaker_id == "spk_a"
        assert rec.path == "a.wav"
        assert rec.environment == "room"

    def test_short_row_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text(
            HEADER + "\na.wav,spk,s,Hi.,mic\n",  # one field short
            encoding="utf-8",
        )
        _write_original(data_in, "a.wav")
        with pytest.raises(HardError, match="fewer fields"):
            read_recordings(data_in)

    def test_long_row_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        data_in.mkdir()
        (data_in / "recordings.csv").write_text(
            HEADER + "\na.wav,spk,s,Hi.,mic,room,surplus\n",  # one field over
            encoding="utf-8",
        )
        _write_original(data_in, "a.wav")
        with pytest.raises(HardError, match="more fields"):
            read_recordings(data_in)


class TestPathResolution:
    def test_missing_original_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, "gone.wav,spk,s,Hi.,mic,room")  # no gone.wav on disk
        with pytest.raises(HardError, match="does not exist"):
            read_recordings(data_in)

    def test_absolute_path_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, "/etc/passwd,spk,s,Hi.,mic,room")
        with pytest.raises(HardError, match="absolute"):
            read_recordings(data_in)

    def test_dotdot_escape_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, "../secret.wav,spk,s,Hi.,mic,room")
        with pytest.raises(HardError, match=r"\.\."):
            read_recordings(data_in)

    def test_dotdot_in_the_middle_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, "sub/../../secret.wav,spk,s,Hi.,mic,room")
        with pytest.raises(HardError, match=r"\.\."):
            read_recordings(data_in)

    def test_backslash_path_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, "sub\\a.wav,spk,s,Hi.,mic,room")
        with pytest.raises(HardError, match="POSIX"):
            read_recordings(data_in)

    def test_empty_path_aborts(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_csv(data_in, ",spk,s,Hi.,mic,room")
        with pytest.raises(HardError, match="empty path"):
            read_recordings(data_in)

    def test_nested_relative_path_resolves(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "spk_a/2026/take.wav", b"nested")
        _write_csv(data_in, "spk_a/2026/take.wav,spk_a,s,Hi.,mic,room")
        rec = _one(read_recordings(data_in))
        assert rec.path == "spk_a/2026/take.wav"


class TestRfc4180:
    def test_quoted_comma_in_prompt_text(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav")
        _write_csv(data_in, 'a.wav,spk,s,"Wait, stop.",mic,room')
        rec = _one(read_recordings(data_in))
        assert rec.prompt_text == "Wait, stop."

    def test_quoted_newline_in_prompt_text(self, tmp_path: Path) -> None:
        data_in = tmp_path / "in"
        _write_original(data_in, "a.wav")
        (data_in / "recordings.csv").write_text(
            HEADER + '\na.wav,spk,s,"line one\nline two",mic,room\n',
            newline="",
            encoding="utf-8",
        )
        rec = _one(read_recordings(data_in))
        # The embedded newline is preserved verbatim in the text; prompt_id collapses it.
        assert "\n" in rec.prompt_text
