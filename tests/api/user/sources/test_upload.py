"""Tests for docsgpt/api/user/sources/upload.py."""

import io
import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "docsgpt.api.user.sources.upload.db_session", _yield
    ), patch(
        "docsgpt.api.user.sources.upload.db_readonly", _yield
    ):
        yield


def _seed_source(pg_conn, user="u", name="src", **kw):
    from docsgpt.storage.db.repositories.sources import SourcesRepository
    return SourcesRepository(pg_conn).create(name, user_id=user, **kw)


class TestEnforceAudioPathSizeLimit:
    def test_noop_for_non_audio(self, tmp_path):
        from docsgpt.api.user.sources.upload import (
            _enforce_audio_path_size_limit,
        )
        p = tmp_path / "doc.txt"
        p.write_bytes(b"x" * 1024)
        _enforce_audio_path_size_limit(str(p), "doc.txt")

    def test_raises_for_large_audio(self, tmp_path):
        from docsgpt.api.user.sources.upload import (
            _enforce_audio_path_size_limit,
        )
        from docsgpt.stt.upload_limits import AudioFileTooLargeError

        p = tmp_path / "audio.mp3"
        p.write_bytes(b"x" * 100)
        with patch(
            "docsgpt.api.user.sources.upload.enforce_audio_file_size_limit",
            side_effect=AudioFileTooLargeError("too large"),
        ):
            with pytest.raises(AudioFileTooLargeError):
                _enforce_audio_path_size_limit(str(p), "audio.mp3")


class TestSafeRelativeUploadPath:
    def test_keeps_nested_folders(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        assert _safe_relative_upload_path("docs/guide/a.md", {}) == "docs/guide/a.md"

    def test_plain_name_stays_flat(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        assert _safe_relative_upload_path("report.pdf", {}) == "report.pdf"

    def test_drops_traversal_and_empty_parts(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        assert _safe_relative_upload_path("../../etc/passwd", {}) == "etc/passwd"
        assert _safe_relative_upload_path("/abs//./x.md", {}) == "abs/x.md"
        assert _safe_relative_upload_path("a\\..\\b.md", {}) == "a/b.md"

    def test_sanitizes_each_part(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        assert _safe_relative_upload_path("my docs/read me.md", {}) == "my_docs/read_me.md"

    def test_unnamed_folder_keeps_its_files_together(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        folder_names: dict[str, str] = {}
        first = _safe_relative_upload_path("文档/a.md", folder_names)
        second = _safe_relative_upload_path("文档/b.md", folder_names)

        assert first.split("/")[0] == second.split("/")[0]
        assert first.endswith("/a.md") and second.endswith("/b.md")

    def test_empty_name_gets_generated_name(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        assert _safe_relative_upload_path("../..", {}) not in ("", ".", "..")

    def test_folders_that_clean_up_the_same_stay_apart(self):
        from docsgpt.api.user.sources.upload import _safe_relative_upload_path

        folder_names: dict[str, str] = {}
        first = _safe_relative_upload_path("docs/my docs/README.md", folder_names)
        second = _safe_relative_upload_path("docs/my_docs/README.md", folder_names)
        again = _safe_relative_upload_path("docs/my docs/b.md", folder_names)

        assert first == "docs/my_docs/README.md"
        assert second == "docs/my_docs_2/README.md"
        assert again == "docs/my_docs/b.md"


class TestUniqueUploadPath:
    def test_free_path_is_kept(self):
        from docsgpt.api.user.sources.upload import _unique_upload_path

        assert _unique_upload_path("docs/a.md", {"docs/b.md"}) == "docs/a.md"

    def test_taken_path_gets_next_free_number(self):
        from docsgpt.api.user.sources.upload import _unique_upload_path

        taken = {"docs/a.md", "docs/a_2.md"}
        assert _unique_upload_path("docs/a.md", taken) == "docs/a_3.md"
        assert _unique_upload_path("docs", {"docs"}) == "docs_2"


class TestUniqueFilePath:
    def test_free_path_is_kept(self):
        from docsgpt.api.user.sources.upload import _unique_file_path

        assert _unique_file_path("docs/a.md", {"docs/b.md"}) == "docs/a.md"
        assert _unique_file_path("docs/a.md", {"docs_2"}) == "docs/a.md"

    def test_same_path_gets_next_free_number(self):
        from docsgpt.api.user.sources.upload import _unique_file_path

        taken = {"docs/a.md", "docs/a_2.md"}
        assert _unique_file_path("docs/a.md", taken) == "docs/a_3.md"

    def test_folder_part_is_renamed_when_a_file_has_its_name(self):
        from docsgpt.api.user.sources.upload import _unique_file_path

        assert _unique_file_path("docs/a.md", {"docs"}) == "docs_2/a.md"
        assert (
            _unique_file_path("docs/a.md", {"docs", "docs_2"}) == "docs_3/a.md"
        )

    def test_file_is_renamed_when_a_folder_has_its_name(self):
        from docsgpt.api.user.sources.upload import _unique_file_path

        assert _unique_file_path("docs", {"docs/a.md"}) == "docs_2"
        assert _unique_file_path("docs", {"docs/a.md", "docs_2"}) == "docs_3"


class TestUploadFile:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        with app.test_request_context("/api/upload", method="POST"):
            from flask import request
            request.decoded_token = None
            response = UploadFile().post()
        assert response.status_code == 401

    def test_returns_400_missing_fields(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "u"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_returns_400_empty_filenames(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        with app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "u", "name": "job",
                "file": (io.BytesIO(b""), ""),  # empty filename
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_uploads_single_file_successfully(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        fake_task = MagicMock(id="task-1")

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "my_job",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["task_id"] == "task-1"

    def test_rejects_file_over_configured_upload_limit(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        with patch(
            "docsgpt.api.user.sources.upload.settings.UPLOAD_MAX_FILE_BYTES",
            4,
        ), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
        ) as apply_async, app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (io.BytesIO(b"12345"), "large.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        assert response.status_code == 413
        fake_storage.save_file.assert_not_called()
        apply_async.assert_not_called()

    def test_storage_error_returns_400(self, app):
        from docsgpt.api.user.sources.upload import UploadFile

        fake_storage = MagicMock()
        fake_storage.save_file.side_effect = RuntimeError("boom")

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"content"), "doc.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 400

    def test_uploads_zip_extracts_files(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        # Build an in-memory zip containing 2 files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("a.txt", "content a")
            zf.writestr("sub/b.txt", "content b")
        zip_buffer.seek(0)

        fake_storage = MagicMock()
        fake_task = MagicMock(id="task-zip")

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (zip_buffer, "docs.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        # save_file called at least twice (for 2 files in zip)
        assert fake_storage.save_file.call_count >= 2

    def test_rejects_zip_with_excessive_expansion_ratio(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.txt", b"A" * (1024 * 1024))
        zip_buffer.seek(0)

        fake_storage = MagicMock()
        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
        ) as apply_async, app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (zip_buffer, "bomb.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        assert response.status_code == 413
        fake_storage.save_file.assert_not_called()
        apply_async.assert_not_called()

    def test_accepts_highly_compressible_csv(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("export.csv", b"a,b,c\n" * 900_000)
        zip_buffer.seek(0)

        fake_storage = MagicMock()
        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="csv-task"),
        ), app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "alice",
                "name": "job",
                "file": (zip_buffer, "export.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        assert response.status_code == 200
        assert fake_storage.save_file.call_count == 1

    def test_archive_error_names_file_and_escapes_log_controls(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("../bad\nFORGED", b"bad")
        zip_buffer.seek(0)

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), patch.object(app.logger, "warning") as warning, app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "alice",
                "name": "job",
                "file": (zip_buffer, "documents.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        assert response.status_code == 413
        assert response.json["message"] == (
            "documents.zip: ZIP archive failed safety validation"
        )
        assert "bad" not in response.json["message"]
        assert "\n" not in response.json["message"]
        logged_values = " ".join(str(value) for value in warning.call_args.args)
        assert "bad\\x0aFORGED" in logged_values
        assert "\n" not in logged_values

    def test_expands_nested_zip_before_storage(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("inside.txt", b"inside")
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("inner.zip", inner.getvalue())
        outer.seek(0)

        fake_storage = MagicMock()
        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="nested-task"),
        ), app.test_request_context(
            "/api/upload",
            method="POST",
            data={
                "user": "alice",
                "name": "job",
                "file": (outer, "outer.zip"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        assert response.status_code == 200
        saved_paths = [call.args[1] for call in fake_storage.save_file.call_args_list]
        assert any(path.endswith("/inner/inside.txt") for path in saved_paths)
        assert not any(path.endswith(".zip") for path in saved_paths)

    def test_office_format_zip_saved_as_is(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        import zipfile

        # .docx is technically a zip but should be saved as-is
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", "<x/>")
        buf.seek(0)

        fake_storage = MagicMock()

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="t"),
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "job",
                "file": (buf, "letter.docx"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 200
        # Saved once (as the .docx directly, not extracted)
        assert fake_storage.save_file.call_count == 1

    def _post_files(self, app, files):
        """Upload ``files`` as job ``job``; return (response, saved files, ingest kwargs).

        ``saved`` maps each storage path to the bytes written there.
        """
        from docsgpt.api.user.sources.upload import UploadFile

        saved: dict[str, bytes] = {}
        fake_storage = MagicMock()
        fake_storage.save_file.side_effect = (
            lambda file, path: saved.__setitem__(path, file.read())
        )
        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="folder-task"),
        ) as apply_async, app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "alice", "name": "job", "file": files},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert fake_storage.save_file.call_count == len(saved)
        kwargs = apply_async.call_args.kwargs["kwargs"] if apply_async.called else None
        return response, saved, kwargs

    def test_folder_upload_keeps_relative_paths(self, app):
        from docsgpt.core.settings import settings

        response, saved, kwargs = self._post_files(app, [
            (io.BytesIO(b"a"), "docs/guide/a.md"),
            (io.BytesIO(b"b"), "docs/b.md"),
        ])

        assert response.status_code == 200
        base_path = f"{settings.UPLOAD_FOLDER}/alice/job"
        assert sorted(saved) == [
            f"{base_path}/docs/b.md",
            f"{base_path}/docs/guide/a.md",
        ]
        assert kwargs["file_path"] == base_path
        assert kwargs["file_name_map"] == {
            "docs/guide/a.md": "a.md",
            "docs/b.md": "b.md",
        }

    def test_plain_file_name_saved_at_source_root(self, app):
        from docsgpt.core.settings import settings

        response, saved, kwargs = self._post_files(
            app, [(io.BytesIO(b"x"), "my notes.txt")]
        )

        assert response.status_code == 200
        assert list(saved) == [f"{settings.UPLOAD_FOLDER}/alice/job/my_notes.txt"]
        assert kwargs["file_name_map"] == {"my_notes.txt": "my notes.txt"}

    def test_folder_upload_cannot_escape_source_dir(self, app):
        from docsgpt.core.settings import settings

        response, saved, _ = self._post_files(app, [
            (io.BytesIO(b"1"), "../../x.md"),
            (io.BytesIO(b"2"), "/etc/y.md"),
            (io.BytesIO(b"3"), "docs/./../z.md"),
            (io.BytesIO(b"4"), "..\\..\\w.md"),
        ])

        assert response.status_code == 200
        base_path = f"{settings.UPLOAD_FOLDER}/alice/job"
        assert sorted(saved) == [
            f"{base_path}/docs/z.md",
            f"{base_path}/etc/y.md",
            f"{base_path}/w.md",
            f"{base_path}/x.md",
        ]
        for path in saved:
            assert ".." not in path.split("/")

    def test_zip_inside_folder_extracts_into_that_folder(self, app):
        import zipfile

        from docsgpt.core.settings import settings

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inside.txt", "inside")
        archive.seek(0)

        response, saved, _ = self._post_files(
            app, [(archive, "docs/bundle.zip")]
        )

        assert response.status_code == 200
        assert list(saved) == [f"{settings.UPLOAD_FOLDER}/alice/job/docs/inside.txt"]

    def test_folders_that_clean_up_the_same_keep_both_files(self, app):
        from docsgpt.core.settings import settings

        response, saved, kwargs = self._post_files(app, [
            (io.BytesIO(b"spaced"), "docs/my docs/README.md"),
            (io.BytesIO(b"underscored"), "docs/my_docs/README.md"),
        ])

        assert response.status_code == 200
        base_path = f"{settings.UPLOAD_FOLDER}/alice/job"
        assert saved == {
            f"{base_path}/docs/my_docs/README.md": b"spaced",
            f"{base_path}/docs/my_docs_2/README.md": b"underscored",
        }
        assert kwargs["file_name_map"] == {
            "docs/my_docs/README.md": "README.md",
            "docs/my_docs_2/README.md": "README.md",
        }

    def test_loose_file_and_zip_member_with_same_path_both_kept(self, app):
        import zipfile

        from docsgpt.core.settings import settings

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inside.txt", "zipped")
        archive.seek(0)

        response, saved, kwargs = self._post_files(app, [
            (io.BytesIO(b"loose"), "docs/inside.txt"),
            (archive, "docs/bundle.zip"),
        ])

        assert response.status_code == 200
        base_path = f"{settings.UPLOAD_FOLDER}/alice/job"
        assert saved == {
            f"{base_path}/docs/inside.txt": b"loose",
            f"{base_path}/docs/inside_2.txt": b"zipped",
        }
        assert kwargs["file_name_map"] == {"docs/inside.txt": "inside.txt"}

    def _post_files_to_disk(self, app, tmp_path, files):
        """Upload ``files`` through a real ``LocalStorage`` rooted in ``tmp_path``.

        Returns (response, stored) where ``stored`` maps each path under the
        source directory to the bytes on disk, so a file that clashed with a
        folder and was dropped or overwritten shows up as missing.
        """
        from docsgpt.api.user.sources.upload import UploadFile
        from docsgpt.core.settings import settings
        from docsgpt.storage.local import LocalStorage

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=LocalStorage(base_dir=str(tmp_path)),
        ), patch(
            "docsgpt.api.user.sources.upload.ingest.apply_async",
            return_value=MagicMock(id="folder-task"),
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={"user": "alice", "name": "job", "file": files},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()

        source_dir = tmp_path / settings.UPLOAD_FOLDER / "alice" / "job"
        stored = {
            path.relative_to(source_dir).as_posix(): path.read_bytes()
            for path in source_dir.rglob("*")
            if path.is_file()
        }
        return response, stored

    @pytest.mark.parametrize("folder_first", [True, False])
    def test_file_and_folder_with_same_name_both_stored(
        self, app, tmp_path, folder_first
    ):
        files = [
            (io.BytesIO(b"in folder"), "docs/a.md"),
            (io.BytesIO(b"plain file"), "docs"),
        ]
        if not folder_first:
            files.reverse()

        response, stored = self._post_files_to_disk(app, tmp_path, files)

        assert response.status_code == 200
        assert sorted(stored.values()) == [b"in folder", b"plain file"]

    @pytest.mark.parametrize("zip_first", [True, False])
    def test_loose_file_and_zip_member_with_same_path_both_stored(
        self, app, tmp_path, zip_first
    ):
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inside.txt", "zipped")
        archive.seek(0)
        files = [
            (io.BytesIO(b"loose"), "docs/inside.txt"),
            (archive, "docs/bundle.zip"),
        ]
        if zip_first:
            files.reverse()

        response, stored = self._post_files_to_disk(app, tmp_path, files)

        assert response.status_code == 200
        assert sorted(stored.values()) == [b"loose", b"zipped"]

    @pytest.mark.parametrize("zip_first", [True, False])
    def test_zip_member_and_file_named_like_its_folder_both_stored(
        self, app, tmp_path, zip_first
    ):
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inside.txt", "zipped")
        archive.seek(0)
        files = [
            (io.BytesIO(b"plain file"), "docs"),
            (archive, "docs/bundle.zip"),
        ]
        if zip_first:
            files.reverse()

        response, stored = self._post_files_to_disk(app, tmp_path, files)

        assert response.status_code == 200
        assert sorted(stored.values()) == [b"plain file", b"zipped"]

    def test_audio_too_large_returns_413(self, app):
        from docsgpt.api.user.sources.upload import UploadFile
        from docsgpt.stt.upload_limits import AudioFileTooLargeError

        fake_storage = MagicMock()

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.sources.upload._enforce_audio_path_size_limit",
            side_effect=AudioFileTooLargeError("too large"),
        ), app.test_request_context(
            "/api/upload", method="POST",
            data={
                "user": "alice", "name": "j",
                "file": (io.BytesIO(b"audio-content"), "song.mp3"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "alice"}
            response = UploadFile().post()
        assert response.status_code == 413


class TestUploadRemote:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u", "source": "github"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = None
            response = UploadRemote().post()
        assert response.status_code == 401

    def test_returns_missing_fields(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        with app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        # check_required_fields returns a response; status is 400
        # The response is returned directly by missing_fields branch
        assert response.status_code == 400

    def test_uploads_github_remote_success(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="remote-task-1")
        with patch(
            "docsgpt.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "gh",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200
        assert response.json["task_id"] == "remote-task-1"

    def test_uploads_url_source(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="url-task")
        with patch(
            "docsgpt.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "crawler", "name": "crawl",
                "data": json.dumps({"url": "https://example.com"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200

    def _post_website(self, app, data):
        from docsgpt.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="website-task")
        with patch(
            "docsgpt.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ) as apply_async, app.test_request_context(
            "/api/remote", method="POST",
            data={"user": "u", "source": "website", "name": "Docs", **data},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        return response, apply_async

    def test_uploads_website_source_with_its_config_and_sync(self, app):
        config = {
            "entries": [{"url": "https://docs.example.com/", "mode": "site", "max_pages": 50}],
            "keep_links": True,
        }
        response, apply_async = self._post_website(
            app, {"data": json.dumps(config), "sync_frequency": "weekly"},
        )

        assert response.status_code == 200
        kwargs = apply_async.call_args.kwargs["kwargs"]
        assert kwargs["loader"] == "website"
        assert kwargs["sync_frequency"] == "weekly"
        # The validated config is what gets stored and synced.
        assert kwargs["source_data"]["entries"][0]["discovery"] == "auto"
        assert kwargs["source_data"]["keep_links"] is True

    def test_a_page_given_twice_is_stored_once(self, app):
        config = {"entries": [
            {"url": "https://docs.example.com/a", "mode": "page"},
            {"url": "https://docs.example.com/b", "mode": "page"},
            # The same page as the first, written another way.
            {"url": "docs.example.com/a/", "mode": "page"},
            {"url": "https://www.docs.example.com/a#intro", "mode": "page"},
            {"url": "https://docs.example.com/", "mode": "site"},
        ]}
        response, apply_async = self._post_website(app, {"data": json.dumps(config)})

        assert response.status_code == 200
        entries = apply_async.call_args.kwargs["kwargs"]["source_data"]["entries"]
        assert [(entry["url"], entry["mode"]) for entry in entries] == [
            ("https://docs.example.com/a", "page"),
            ("https://docs.example.com/b", "page"),
            ("https://docs.example.com/", "site"),
        ]

    def test_website_source_defaults_to_no_sync(self, app):
        config = {"entries": [{"url": "https://docs.example.com/a", "mode": "page"}]}
        response, apply_async = self._post_website(app, {"data": json.dumps(config)})

        assert response.status_code == 200
        assert apply_async.call_args.kwargs["kwargs"]["sync_frequency"] == "never"

    def test_website_source_with_a_bad_config_is_400(self, app):
        response, apply_async = self._post_website(app, {"data": json.dumps({"entries": []})})

        assert response.status_code == 400
        assert "at least one" in response.json["error"]
        # A config error without a code of its own is still one the UI can word.
        assert response.json["code"] == "invalid_config"
        apply_async.assert_not_called()

    def test_a_website_config_error_passes_on_its_code_and_details(self, app):
        class ConfigError(ValueError):
            code = "page_limit"
            details = {"max_pages": 500}

        config = {"entries": [{"url": "https://docs.example.com/a", "mode": "page"}]}
        with patch(
            "docsgpt.api.user.sources.upload.parse_website_config",
            side_effect=ConfigError("A website source holds up to 500 pages"),
        ):
            response, apply_async = self._post_website(app, {"data": json.dumps(config)})

        assert response.status_code == 400
        assert response.json == {
            "success": False, "error": "A website source holds up to 500 pages", "code": "page_limit",
            "max_pages": 500,
        }
        apply_async.assert_not_called()

    def test_website_source_with_an_unknown_sync_frequency_is_400(self, app):
        config = {"entries": [{"url": "https://docs.example.com/a", "mode": "page"}]}
        response, apply_async = self._post_website(
            app, {"data": json.dumps(config), "sync_frequency": "hourly"},
        )

        assert response.status_code == 400
        assert response.json["code"] == "bad_sync_frequency"
        apply_async.assert_not_called()

    def test_uploads_reddit_source(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        fake_task = MagicMock(id="reddit-task")
        with patch(
            "docsgpt.api.user.sources.upload.ingest_remote.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "reddit", "name": "r",
                "data": json.dumps({"subreddit": "python"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 200

    def test_upload_exception_returns_400(self, app):
        from docsgpt.api.user.sources.upload import UploadRemote

        with patch(
            "docsgpt.api.user.sources.upload.ingest_remote.apply_async",
            side_effect=RuntimeError("boom"),
        ), app.test_request_context(
            "/api/remote", method="POST",
            data={
                "user": "u", "source": "github", "name": "x",
                "data": json.dumps({"repo_url": "https://github.com/x/y"}),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UploadRemote().post()
        assert response.status_code == 400


class TestManageSourceFiles:
    def test_returns_401_unauthenticated(self, app):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x", "operation": "add"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = None
            response = ManageSourceFiles().post()
        assert response.status_code == 401

    def test_returns_400_missing_required(self, app):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_returns_400_invalid_operation(self, app):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        with app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": "x", "operation": "weird"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_returns_404_source_not_found(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        with _patch_db(pg_conn), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": "00000000-0000-0000-0000-000000000000",
                "operation": "add",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ManageSourceFiles().post()
        assert response.status_code == 404

    def test_rejects_bad_parent_dir(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-bad-parent"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "add",
                "parent_dir": "/abs-path",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_add_no_files_returns_400(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-add-nofile"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(src["id"]), "operation": "add"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_add_rejects_file_over_upload_limit(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-add-large"
        src = _seed_source(pg_conn, user=user, file_path="/data/src")
        fake_storage = MagicMock()
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.upload_limits.settings.UPLOAD_MAX_FILE_BYTES", 4
        ), patch(
            "docsgpt.api.user.tasks.reingest_source_task.apply_async"
        ) as apply_async, app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "add",
                "file": (io.BytesIO(b"12345"), "large.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()

        assert response.status_code == 413
        fake_storage.save_file.assert_not_called()
        apply_async.assert_not_called()

    def test_add_files_success(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-add-ok"
        src = _seed_source(pg_conn, user=user, file_path="/data/src")

        fake_storage = MagicMock()
        fake_task = MagicMock(id="reingest-1")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "add",
                "file": (io.BytesIO(b"content"), "new.txt"),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert response.json["success"] is True
        assert "new.txt" in response.json["added_files"]

    def test_each_keyless_change_dispatches_its_own_reingest_key(self, app, pg_conn):
        """Without an Idempotency-Key, two file changes must not share a key:
        the task's guard would replay the first reingest for 24h instead of
        embedding the second change.
        """
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-add-twice"
        src = _seed_source(pg_conn, user=user, file_path="/data/src")
        keys = []
        for name in ("one.txt", "two.txt"):
            with _patch_db(pg_conn), patch(
                "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
                return_value=MagicMock(),
            ), patch(
                "docsgpt.api.user.tasks.reingest_source_task.apply_async",
                return_value=MagicMock(id="reingest-1"),
            ) as mock_apply, app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={
                    "source_id": str(src["id"]),
                    "operation": "add",
                    "file": (io.BytesIO(b"content"), name),
                },
                content_type="multipart/form-data",
            ):
                from flask import request
                request.decoded_token = {"sub": user}
                response = ManageSourceFiles().post()
            assert response.status_code == 200
            keys.append(mock_apply.call_args.kwargs["kwargs"]["idempotency_key"])

        assert all(key and key.startswith(f"reingest-source:{user}:{src['id']}:") for key in keys)
        assert keys[0] != keys[1]

    def test_remove_missing_file_paths_returns_400(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-nolist"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(src["id"]), "operation": "remove"},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_invalid_json_file_paths(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-bad"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": "not-json",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_rejects_path_traversal(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-trav"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": json.dumps(["../escape.txt"]),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_files_success(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rm-ok"
        src = _seed_source(
            pg_conn, user=user,
            file_path="/data/src",
            file_name_map={"a.txt": "Original A.txt"},
        )

        fake_storage = MagicMock()
        fake_storage.file_exists.return_value = True
        fake_task = MagicMock(id="reingest-rm")
        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ) as apply_async, app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove",
                "file_paths": json.dumps(["a.txt"]),
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert "a.txt" in response.json["removed_files"]
        # The caller receives the reingest's events (a team editor isn't the owner).
        assert apply_async.call_args.kwargs["kwargs"]["actor_id"] == user

    def test_remove_directory_missing_path(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-missing"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_directory_rejects_bad_path(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-bad"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=MagicMock(),
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "../escape",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 400

    def test_remove_directory_404_when_not_directory(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-notdir"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "subdir",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 404

    def test_remove_directory_success(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-ok"
        src = _seed_source(
            pg_conn, user=user, file_path="/data",
            file_name_map={"sub/a.txt": "A"},
        )

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = True
        fake_storage.remove_directory.return_value = True
        fake_task = MagicMock(id="reingest-dir")

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), patch(
            "docsgpt.api.user.tasks.reingest_source_task.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "sub",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 200
        assert response.json["removed_directory"] == "sub"

    def test_remove_directory_storage_failure_returns_500(self, app, pg_conn):
        from docsgpt.api.user.sources.upload import ManageSourceFiles

        user = "u-rmdir-fail"
        src = _seed_source(pg_conn, user=user, file_path="/data")

        fake_storage = MagicMock()
        fake_storage.is_directory.return_value = True
        fake_storage.remove_directory.return_value = False

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=fake_storage,
        ), app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={
                "source_id": str(src["id"]),
                "operation": "remove_directory",
                "directory_path": "sub",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        assert response.status_code == 500


class TestManageSourceFilesSync:
    """``sync`` makes the upload the source's whole file set, then reingests."""

    def _seed(self, pg_conn, tmp_path, files, user="u-sync", **kw):
        root = tmp_path / "inputs" / user / "src"
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        kw.setdefault("file_path", f"inputs/{user}/src")
        return _seed_source(pg_conn, user=user, **kw), root

    def _sync(self, app, pg_conn, tmp_path, src, files, user="u-sync", storage=None, **form):
        from docsgpt.api.user.sources.upload import ManageSourceFiles
        from docsgpt.storage.local import LocalStorage

        with _patch_db(pg_conn), patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=storage or LocalStorage(base_dir=str(tmp_path)),
        ), patch(
            "docsgpt.api.user.tasks.reingest_source_task.apply_async",
            return_value=MagicMock(id="reingest-sync"),
        ) as apply_async, app.test_request_context(
            "/api/manage_source_files", method="POST",
            data={"source_id": str(src["id"]), "operation": "sync", "file": files, **form},
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = ManageSourceFiles().post()
        return response, apply_async

    @staticmethod
    def _stored(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def test_upload_becomes_the_whole_file_set(self, app, pg_conn, tmp_path):
        src, root = self._seed(pg_conn, tmp_path, {
            "keep.md": b"same", "old.md": b"stale", "docs/edit.md": b"v1",
        })

        response, apply_async = self._sync(app, pg_conn, tmp_path, src, [
            (io.BytesIO(b"same"), "keep.md"),
            (io.BytesIO(b"v2"), "docs/edit.md"),
            (io.BytesIO(b"hello"), "new.md"),
        ])

        assert response.status_code == 200
        assert response.json["reingest_task_id"] == "reingest-sync"
        assert response.json["source_id"] == str(src["id"])
        assert response.json["removed_files"] == ["old.md"]
        assert self._stored(root) == {"keep.md": b"same", "docs/edit.md": b"v2", "new.md": b"hello"}
        kwargs = apply_async.call_args.kwargs["kwargs"]
        assert kwargs["source_id"] == str(src["id"]) and kwargs["user"] == "u-sync"

    def test_an_upload_with_no_files_inside_is_refused(self, app, pg_conn, tmp_path):
        import zipfile

        src, root = self._seed(pg_conn, tmp_path, {"keep.md": b"same"})
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("empty-folder/", "")
        archive.seek(0)

        response, apply_async = self._sync(app, pg_conn, tmp_path, src, [(archive, "docs.zip")])

        assert response.status_code == 400
        assert self._stored(root) == {"keep.md": b"same"}
        apply_async.assert_not_called()

    def test_removes_files_from_a_store_that_lists_with_backslashes(self, app, pg_conn, tmp_path):
        from docsgpt.storage.local import LocalStorage

        src, root = self._seed(pg_conn, tmp_path, {"keep.md": b"same", "old.md": b"stale"})

        class WindowsListing(LocalStorage):
            """Lists as ``LocalStorage`` does on Windows, with backslash separators."""

            def list_files(self, directory):
                return [path.replace("/", "\\") for path in super().list_files(directory)]

            def delete_file(self, path):
                return super().delete_file(path.replace("\\", "/"))

        response, _ = self._sync(
            app, pg_conn, tmp_path, src, [(io.BytesIO(b"same"), "keep.md")],
            storage=WindowsListing(base_dir=str(tmp_path)),
        )

        assert response.status_code == 200
        assert response.json["removed_files"] == ["old.md"]
        assert self._stored(root) == {"keep.md": b"same"}

    def test_never_deletes_outside_the_source_folder(self, app, pg_conn, tmp_path):
        from docsgpt.storage.local import LocalStorage

        src, root = self._seed(pg_conn, tmp_path, {"old.md": b"stale"})
        sibling = tmp_path / "inputs" / "u-sync" / "src-2" / "theirs.md"
        sibling.parent.mkdir(parents=True)
        sibling.write_bytes(b"keep me")

        class PrefixListing(LocalStorage):
            """A store that lists by bare prefix, as an object store without a trailing slash would."""

            def list_files(self, directory):
                return super().list_files(directory) + ["inputs/u-sync/src-2/theirs.md"]

        with patch(
            "docsgpt.api.user.sources.upload.StorageCreator.get_storage",
            return_value=PrefixListing(base_dir=str(tmp_path)),
        ):
            from docsgpt.api.user.sources.upload import ManageSourceFiles

            with _patch_db(pg_conn), patch(
                "docsgpt.api.user.tasks.reingest_source_task.apply_async",
                return_value=MagicMock(id="reingest-sync"),
            ), app.test_request_context(
                "/api/manage_source_files", method="POST",
                data={"source_id": str(src["id"]), "operation": "sync", "file": [(io.BytesIO(b"new"), "new.md")]},
                content_type="multipart/form-data",
            ):
                from flask import request
                request.decoded_token = {"sub": "u-sync"}
                response = ManageSourceFiles().post()

        assert response.status_code == 200
        assert response.json["removed_files"] == ["old.md"]
        assert sibling.read_bytes() == b"keep me"

    def test_a_zip_is_unpacked_keeping_its_folders(self, app, pg_conn, tmp_path):
        import zipfile

        src, root = self._seed(pg_conn, tmp_path, {"content/old.md": b"stale"})
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("content/a.md", "a")
            zf.writestr("content/guide/b.md", "b")
        archive.seek(0)

        response, _ = self._sync(app, pg_conn, tmp_path, src, [(archive, "docs.zip")])

        assert response.status_code == 200
        assert self._stored(root) == {"content/a.md": b"a", "content/guide/b.md": b"b"}

    def test_file_name_map_follows_the_new_files(self, app, pg_conn, tmp_path):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        src, _ = self._seed(
            pg_conn, tmp_path, {"old.md": b"x"}, file_name_map={"old.md": "Old notes.md"},
        )

        self._sync(app, pg_conn, tmp_path, src, [(io.BytesIO(b"r"), "Q3 report.md")])

        row = SourcesRepository(pg_conn).get(str(src["id"]), "u-sync")
        assert row["file_name_map"] == {"Q3_report.md": "Q3 report.md"}

    def test_an_unsafe_zip_changes_nothing(self, app, pg_conn, tmp_path):
        import zipfile

        src, root = self._seed(pg_conn, tmp_path, {"keep.md": b"same"})
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("a.md", "a")
            zf.writestr("b.md", "b")
        archive.seek(0)

        with patch("docsgpt.api.user.sources.upload.settings.UPLOAD_MAX_ARCHIVE_FILES", 1):
            response, apply_async = self._sync(app, pg_conn, tmp_path, src, [(archive, "docs.zip")])

        assert response.status_code == 413
        assert self._stored(root) == {"keep.md": b"same"}
        apply_async.assert_not_called()

    def test_no_files_returns_400(self, app, pg_conn, tmp_path):
        src, root = self._seed(pg_conn, tmp_path, {"keep.md": b"same"})

        response, apply_async = self._sync(app, pg_conn, tmp_path, src, [])

        assert response.status_code == 400
        assert self._stored(root) == {"keep.md": b"same"}
        apply_async.assert_not_called()

    def test_a_source_without_stored_files_is_refused(self, app, pg_conn, tmp_path):
        src, _ = self._seed(pg_conn, tmp_path, {}, file_path="")
        (tmp_path / "unrelated.md").write_bytes(b"x")

        response, apply_async = self._sync(app, pg_conn, tmp_path, src, [(io.BytesIO(b"a"), "a.md")])

        assert response.status_code == 400
        assert (tmp_path / "unrelated.md").exists()
        apply_async.assert_not_called()

    def test_parent_dir_is_refused(self, app, pg_conn, tmp_path):
        src, root = self._seed(pg_conn, tmp_path, {"keep.md": b"same"})

        response, apply_async = self._sync(
            app, pg_conn, tmp_path, src, [(io.BytesIO(b"a"), "a.md")], parent_dir="docs",
        )

        assert response.status_code == 400
        assert self._stored(root) == {"keep.md": b"same"}
        apply_async.assert_not_called()


def _task_status(app, task_id, *, owner=None, user=None, celery_mock=None, owners_down=False):
    """Call TaskStatus for ``task_id`` with a recorded owner and a caller."""
    from docsgpt.api.user.sources.upload import TaskStatus
    from docsgpt.api.user.task_owners import TaskOwnersUnavailable

    lookup = MagicMock(return_value=owner)
    if owners_down:
        lookup.side_effect = TaskOwnersUnavailable()
    url = "/api/task_status" + (f"?task_id={task_id}" if task_id else "")
    with patch("docsgpt.api.user.sources.upload.get_task_owner", lookup), patch(
        "docsgpt.celery_init.celery", celery_mock or MagicMock()
    ), app.test_request_context(url):
        from flask import request
        request.decoded_token = {"sub": user} if user else None
        return TaskStatus().get()


def _celery_with(status, info=None, workers=True):
    fake_task = MagicMock()
    fake_task.status = status
    fake_task.info = info
    fake_celery = MagicMock()
    fake_celery.AsyncResult.return_value = fake_task
    fake_celery.control.inspect.return_value.ping.return_value = {"w": "pong"} if workers else None
    return fake_celery


class TestTaskStatus:
    def test_returns_400_missing_task_id(self, app):
        response = _task_status(app, None, user="alice")
        assert response.status_code == 400

    def test_owner_reads_status(self, app):
        fake_celery = _celery_with("SUCCESS", {"result": "ok"})
        response = _task_status(app, "t-123", owner="alice", user="alice", celery_mock=fake_celery)
        assert response.status_code == 200
        assert response.json["status"] == "SUCCESS"

    def test_other_user_gets_404(self, app):
        fake_celery = _celery_with("SUCCESS", {"answer": "secret"})
        response = _task_status(app, "t-123", owner="alice", user="mallory", celery_mock=fake_celery)
        assert response.status_code == 404
        assert "secret" not in response.get_data(as_text=True)
        fake_celery.AsyncResult.assert_not_called()

    def test_anonymous_caller_gets_404_for_user_task(self, app):
        fake_celery = _celery_with("SUCCESS", {"answer": "secret"})
        response = _task_status(app, "t-123", owner="alice", user=None, celery_mock=fake_celery)
        assert response.status_code == 404
        fake_celery.AsyncResult.assert_not_called()

    def test_unknown_task_gets_404_without_pinging_workers(self, app):
        fake_celery = _celery_with("PENDING", workers=False)
        response = _task_status(app, "t-unknown", owner=None, user="alice", celery_mock=fake_celery)
        assert response.status_code == 404
        fake_celery.control.inspect.assert_not_called()

    def test_capability_task_readable_without_session(self, app):
        """Webhook and agent api_key tasks: the task id is the credential."""
        fake_celery = _celery_with("SUCCESS", {"status": "success"})
        response = _task_status(app, "t-hook", owner="", user=None, celery_mock=fake_celery)
        assert response.status_code == 200
        assert response.json["result"] == {"status": "success"}

    def test_capability_task_readable_with_any_session(self, app):
        fake_celery = _celery_with("SUCCESS", {"status": "success"})
        response = _task_status(app, "t-hook", owner="", user="bob", celery_mock=fake_celery)
        assert response.status_code == 200

    def test_owner_store_down_returns_503(self, app):
        fake_celery = _celery_with("SUCCESS")
        response = _task_status(app, "t-123", user="alice", celery_mock=fake_celery, owners_down=True)
        assert response.status_code == 503
        fake_celery.AsyncResult.assert_not_called()

    def test_pending_without_workers_returns_503(self, app):
        fake_celery = _celery_with("PENDING", workers=False)
        response = _task_status(app, "t-999", owner="alice", user="alice", celery_mock=fake_celery)
        assert response.status_code == 503

    def test_exception_returns_400(self, app):
        fake_celery = MagicMock()
        fake_celery.AsyncResult.side_effect = RuntimeError("boom")
        response = _task_status(app, "t-err", owner="alice", user="alice", celery_mock=fake_celery)
        assert response.status_code == 400

    def test_non_serializable_info_gets_stringified(self, app):
        class WeirdObj:
            def __str__(self):
                return "weird-str"

        fake_celery = _celery_with("SUCCESS", WeirdObj())
        response = _task_status(app, "t-weird", owner="alice", user="alice", celery_mock=fake_celery)
        assert response.status_code == 200
        assert response.json["result"] == "weird-str"
