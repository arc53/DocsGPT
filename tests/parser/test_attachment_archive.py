"""Unpacking a zip attachment into its member files, within limits."""

from __future__ import annotations

import io
import os
import random
import zipfile

import pytest

from docsgpt.parser.attachment_archive import (
    ArchiveLimits,
    ArchiveRejectedError,
    expand_archive,
)

pytestmark = pytest.mark.unit

LIMITS = ArchiveLimits(max_members=200, max_total_bytes=10 * 1024 * 1024, max_depth=2, max_ratio=100)


def _zip_bytes(entries, *, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buffer.getvalue()


def _write_zip(tmp_path, entries, name="upload.zip", **kwargs):
    path = tmp_path / name
    path.write_bytes(_zip_bytes(entries, **kwargs))
    return str(path)


def _expand(tmp_path, entries, limits=LIMITS, **kwargs):
    dest = tmp_path / "out"
    dest.mkdir(exist_ok=True)
    return expand_archive(_write_zip(tmp_path, entries, **kwargs), str(dest), limits)


class TestMembers:
    def test_members_in_archive_order_with_their_paths(self, tmp_path):
        result = _expand(tmp_path, [("b.txt", b"bee"), ("dir/a.csv", b"x,y\n1,2\n"), ("dir/sub/c.md", b"# c")])
        assert [m.archive_path for m in result.members] == ["b.txt", "dir/a.csv", "dir/sub/c.md"]
        assert [m.filename for m in result.members] == ["b.txt", "a.csv", "c.md"]
        assert [m.size for m in result.members] == [3, 8, 3]
        for member in result.members:
            assert os.path.isfile(member.local_path)
            assert member.local_path.startswith(str(tmp_path / "out"))
        assert open(result.members[1].local_path, "rb").read() == b"x,y\n1,2\n"
        assert result.skipped == []

    def test_directories_and_os_junk_are_ignored(self, tmp_path):
        result = _expand(
            tmp_path,
            [("dir/", b""), ("__MACOSX/._a.txt", b"junk"), ("dir/.DS_Store", b"junk"), ("dir/a.txt", b"a")],
        )
        assert [m.archive_path for m in result.members] == ["dir/a.txt"]
        assert result.skipped == []

    def test_non_ascii_names_keep_their_display_name(self, tmp_path):
        result = _expand(tmp_path, [("отчёт.txt", b"text")])
        assert result.members[0].filename == "отчёт.txt"
        assert os.path.basename(result.members[0].local_path).endswith(".txt")


class TestSafety:
    def test_path_traversal_member_is_skipped_and_never_written_outside(self, tmp_path):
        result = _expand(tmp_path, [("../../evil.txt", b"x"), ("/abs.txt", b"y"), ("ok.txt", b"z")])
        assert [m.archive_path for m in result.members] == ["ok.txt"]
        assert {s.reason for s in result.skipped} == {"unsafe_path"}
        assert len(result.skipped) == 2
        assert not (tmp_path / "evil.txt").exists()
        assert not os.path.exists("/abs.txt") or open("/abs.txt", "rb").read() != b"y"

    def test_a_zip_bomb_is_rejected_whole(self, tmp_path):
        with pytest.raises(ArchiveRejectedError, match="compression"):
            _expand(tmp_path, [("zeros.txt", b"\0" * (5 * 1024 * 1024))])

    def test_an_invalid_zip_is_rejected(self, tmp_path):
        path = tmp_path / "fake.zip"
        path.write_bytes(b"not a zip at all")
        with pytest.raises(ArchiveRejectedError):
            expand_archive(str(path), str(tmp_path), LIMITS)

    def test_encrypted_members_are_skipped(self, tmp_path):
        data = bytearray(_zip_bytes([("secret.txt", b"s"), ("plain.txt", b"p")], compression=zipfile.ZIP_STORED))
        # Set the "encrypted" flag bit on the first member's local and central headers.
        local = data.find(b"PK\x03\x04")
        data[local + 6] |= 0x1
        central = data.find(b"PK\x01\x02")
        data[central + 8] |= 0x1
        path = tmp_path / "enc.zip"
        path.write_bytes(bytes(data))
        result = expand_archive(str(path), str(tmp_path), LIMITS)
        assert [m.archive_path for m in result.members] == ["plain.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("secret.txt", "encrypted")]


class TestLimits:
    def test_members_past_the_count_cap_are_skipped(self, tmp_path):
        limits = ArchiveLimits(max_members=2, max_total_bytes=10**6, max_depth=2, max_ratio=100)
        result = _expand(tmp_path, [(f"f{i}.txt", b"x") for i in range(4)], limits=limits)
        assert [m.archive_path for m in result.members] == ["f0.txt", "f1.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [
            ("f2.txt", "too_many_files"), ("f3.txt", "too_many_files"),
        ]

    def test_members_past_the_byte_cap_are_skipped(self, tmp_path):
        limits = ArchiveLimits(max_members=200, max_total_bytes=10, max_depth=2, max_ratio=100)
        result = _expand(
            tmp_path, [("a.txt", b"12345"), ("b.txt", b"1234567"), ("c.txt", b"12")],
            limits=limits, compression=zipfile.ZIP_STORED,
        )
        assert [m.archive_path for m in result.members] == ["a.txt", "c.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("b.txt", "archive_too_large")]

    def test_one_nested_zip_is_expanded_under_its_path(self, tmp_path):
        inner = _zip_bytes([("d.txt", b"dee")])
        result = _expand(tmp_path, [("a.txt", b"a"), ("sub/inner.zip", inner)], compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["a.txt", "sub/inner.zip/d.txt"]

    def test_deeper_nesting_is_skipped(self, tmp_path):
        innermost = _zip_bytes([("deep.txt", b"deep")])
        inner = _zip_bytes([("inner.txt", b"i"), ("innermost.zip", innermost)], compression=zipfile.ZIP_STORED)
        result = _expand(tmp_path, [("inner.zip", inner)], compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["inner.zip/inner.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [
            ("inner.zip/innermost.zip", "nested_too_deep"),
        ]

    def test_nested_members_count_against_the_same_caps(self, tmp_path):
        limits = ArchiveLimits(max_members=2, max_total_bytes=10**6, max_depth=2, max_ratio=100)
        inner = _zip_bytes([("x.txt", b"x"), ("y.txt", b"y")])
        result = _expand(tmp_path, [("a.txt", b"a"), ("inner.zip", inner)], limits=limits,
                         compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["a.txt", "inner.zip/x.txt"]
        assert [s.reason for s in result.skipped] == ["too_many_files"]

    def test_skipped_list_is_bounded(self, tmp_path):
        limits = ArchiveLimits(max_members=1, max_total_bytes=10**6, max_depth=2, max_ratio=100)
        result = _expand(tmp_path, [(f"f{i}.txt", b"x") for i in range(300)], limits=limits)
        assert len(result.skipped) <= 100
        assert result.skipped_count == 299

    def test_limits_come_from_settings(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_MEMBERS", 7)
        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_BYTES", 8)
        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_DEPTH", 1)
        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_RATIO", 9)
        assert ArchiveLimits.from_settings() == ArchiveLimits(
            max_members=7, max_total_bytes=8, max_depth=1, max_ratio=9
        )


def _corrupt_member(data: bytes, name: str) -> bytes:
    """``data`` with the start of ``name``'s compressed stream overwritten."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    info = archive.getinfo(name)
    offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    damaged = bytearray(data)
    for i in range(offset, offset + 10):
        damaged[i] = 0xFF
    return bytes(damaged)


class TestDamagedMembers:
    @pytest.mark.parametrize(
        "compression", [zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=["deflate", "bzip2", "lzma"]
    )
    def test_a_damaged_member_is_skipped_and_the_rest_unpacked(self, tmp_path, compression):
        data = _zip_bytes([("good.txt", b"hello world " * 200), ("bad.txt", b"abcdefgh" * 500)], compression=compression)
        path = tmp_path / "damaged.zip"
        path.write_bytes(_corrupt_member(data, "bad.txt"))
        dest = tmp_path / "out"
        dest.mkdir()
        result = expand_archive(str(path), str(dest), LIMITS)
        assert [m.archive_path for m in result.members] == ["good.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("bad.txt", "corrupt")]
        assert len(os.listdir(dest)) == 1

    def test_a_member_in_an_unsupported_compression_method_is_skipped(self, tmp_path):
        data = bytearray(_zip_bytes([("odd.txt", b"o"), ("plain.txt", b"p")], compression=zipfile.ZIP_STORED))
        # Compression method 9 (Deflate64) on the first member's local and central headers.
        data[data.find(b"PK\x03\x04") + 8] = 9
        data[data.find(b"PK\x01\x02") + 10] = 9
        path = tmp_path / "method.zip"
        path.write_bytes(bytes(data))
        result = expand_archive(str(path), str(tmp_path), LIMITS)
        assert [m.archive_path for m in result.members] == ["plain.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("odd.txt", "corrupt")]

    def test_a_damaged_member_inside_a_nested_zip_is_skipped(self, tmp_path):
        noise = random.Random(1).randbytes(4000)  # incompressible, so the ratio check passes
        inner = _corrupt_member(_zip_bytes([("bad.txt", noise), ("ok.txt", b"ok")]), "bad.txt")
        result = _expand(tmp_path, [("a.txt", b"a"), ("inner.zip", inner)], compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["a.txt", "inner.zip/ok.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("inner.zip/bad.txt", "corrupt")]


def _txt_only(filename, read_head):
    return filename.endswith(".txt")


class TestEntryLimits:
    def test_unsupported_members_do_not_use_up_the_member_limit(self, tmp_path):
        limits = ArchiveLimits(max_members=2, max_total_bytes=10**6, max_depth=2, max_ratio=100)
        objects = [(f".git/objects/{i:02x}/blob", b"\x00\x01binary") for i in range(5)]
        result = expand_archive(
            _write_zip(tmp_path, [*objects, ("a.txt", b"a"), ("b.txt", b"b")], compression=zipfile.ZIP_STORED),
            str(tmp_path),
            limits,
            accept=_txt_only,
        )
        assert [m.archive_path for m in result.members] == ["a.txt", "b.txt"]
        assert {s.reason for s in result.skipped} == {"unsupported_type"}
        assert result.skipped_count == 5
        assert result.total_bytes == 2

    def test_the_acceptance_check_can_read_the_members_head(self, tmp_path):
        seen = {}

        def accept(filename, read_head):
            seen[filename] = read_head()
            return True

        expand_archive(_write_zip(tmp_path, [("notes.log", b"plain text")]), str(tmp_path), LIMITS, accept=accept)
        assert seen == {"notes.log": b"plain text"}

    def test_entries_past_the_entry_limit_are_skipped_without_unpacking(self, tmp_path):
        limits = ArchiveLimits(max_members=200, max_total_bytes=10**6, max_depth=2, max_ratio=100, max_entries=3)
        result = _expand(tmp_path, [(f"f{i}.bin", b"\x00") for i in range(5)] + [("a.txt", b"a")],
                         limits=limits, compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["f0.bin", "f1.bin", "f2.bin"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [
            ("f3.bin", "too_many_files"), ("f4.bin", "too_many_files"), ("a.txt", "too_many_files"),
        ]

    def test_empty_nested_zips_count_toward_the_entry_limit(self, tmp_path):
        empty = _zip_bytes([])
        limits = ArchiveLimits(max_members=200, max_total_bytes=10**6, max_depth=2, max_ratio=100, max_entries=10)
        result = _expand(tmp_path, [(f"{i}.zip", empty) for i in range(50)], limits=limits,
                         compression=zipfile.ZIP_STORED)
        assert result.members == []
        assert result.skipped_count == 40
        assert {s.reason for s in result.skipped} == {"too_many_files"}

    def test_the_entry_limit_spans_nested_archives(self, tmp_path):
        inner = _zip_bytes([("x.txt", b"x"), ("y.txt", b"y")])
        limits = ArchiveLimits(max_members=200, max_total_bytes=10**6, max_depth=2, max_ratio=100, max_entries=3)
        result = _expand(tmp_path, [("a.txt", b"a"), ("inner.zip", inner), ("b.txt", b"b")], limits=limits,
                         compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["a.txt", "inner.zip/x.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [
            ("inner.zip/y.txt", "too_many_files"), ("b.txt", "too_many_files"),
        ]

    def test_a_member_over_the_per_file_limit_is_skipped(self, tmp_path):
        limits = ArchiveLimits(max_members=200, max_total_bytes=10**6, max_depth=2, max_ratio=100,
                               max_member_bytes=4)
        result = _expand(tmp_path, [("big.txt", b"12345"), ("ok.txt", b"1234")], limits=limits,
                         compression=zipfile.ZIP_STORED)
        assert [m.archive_path for m in result.members] == ["ok.txt"]
        assert [(s.archive_path, s.reason) for s in result.skipped] == [("big.txt", "file_too_large")]

    def test_entry_and_file_limits_come_from_settings(self, monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_ARCHIVE_MAX_ENTRIES", 11)
        monkeypatch.setattr(settings, "UPLOAD_MAX_FILE_BYTES", 12)
        limits = ArchiveLimits.from_settings()
        assert (limits.max_entries, limits.max_member_bytes) == (11, 12)


class TestRejectionReason:
    def test_a_zip_bomb_says_so(self, tmp_path):
        with pytest.raises(ArchiveRejectedError) as raised:
            _expand(tmp_path, [("zeros.txt", b"\0" * (5 * 1024 * 1024))])
        assert raised.value.reason == "zip_bomb"
        assert "could not be read" not in str(raised.value)

    def test_a_zip_bomb_nested_inside_rejects_the_whole_zip(self, tmp_path):
        bomb = _zip_bytes([("zeros.txt", b"\0" * (5 * 1024 * 1024))])
        with pytest.raises(ArchiveRejectedError) as raised:
            _expand(tmp_path, [("a.txt", b"a"), ("inner.zip", bomb)], compression=zipfile.ZIP_STORED)
        assert raised.value.reason == "zip_bomb"

    def test_an_unreadable_zip_says_so(self, tmp_path):
        path = tmp_path / "fake.zip"
        path.write_bytes(b"not a zip at all")
        with pytest.raises(ArchiveRejectedError) as raised:
            expand_archive(str(path), str(tmp_path), LIMITS)
        assert raised.value.reason == "unreadable"
