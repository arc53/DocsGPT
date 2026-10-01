"""/v1 file and image parts become the user's attachment rows."""

import base64
import copy
import hashlib
from pathlib import Path
from typing import Any, Dict

import pytest

from docsgpt.api.v1.translator import (
    apply_converted_files,
    collect_inline_files,
    translate_request,
)
from docsgpt.attachment_names import normalize_attachment_filename
from tests.fixtures.many_attachments import generate as gen
from tests.fixtures.many_attachments import v1_requests as v1

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def scenario_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("v1_parts")
    for sid in ("V1-01", "V1-02", "V1-03"):
        gen.generate_scenario(sid, out, "small")
    return out


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(payload).decode()}"


class TestFilenames:
    @pytest.mark.parametrize(
        "name, mime, expected",
        [
            ("PRILOGA_1.PDF", "application/pdf", "PRILOGA_1.pdf"),
            ("report", "application/pdf", "report.pdf"),
            ("scan.JPEG", "image/jpeg", "scan.jpeg"),
            (None, "image/png", "attachment.png"),
            ("dir/../evil.Docx", None, "evil.docx"),
            ("notes", None, "notes"),
        ],
    )
    def test_extension_is_lower_case_and_present(self, name, mime, expected):
        assert normalize_attachment_filename(name, mime) == expected


class TestCollect:
    def test_upper_case_pdf_parts_are_collected_with_normalized_names(self, scenario_dir: Path):
        step = v1.build_requests("V1-03", scenario_dir, payload="file_parts")[0]
        files = collect_inline_files(step["body"]["messages"])

        assert [f.filename for f in files] == [f"PRILOGA_{i}.pdf" for i in range(1, 5)]
        assert {f.mime_type for f in files} == {"application/pdf"}
        manifest = gen.load_manifest(scenario_dir, "V1-03")
        hashes = {f["sha256"] for f in manifest["files"]}
        assert {f.content_hash for f in files} <= hashes

    def test_files_from_every_user_message_are_collected_once(self, scenario_dir: Path):
        steps = v1.build_requests("V1-01", scenario_dir, payload="file_parts")
        last = steps[-1]["body"]["messages"]
        resent = last + [{"role": "assistant", "content": "ok"}] + copy.deepcopy(last[1:])

        files = collect_inline_files(resent)

        parts = [p for p in last[-1]["content"] if p["type"] == "file"]
        assert len(files) == len({hashlib.sha256(base64.b64decode(p["file"]["file_data"].split(",", 1)[1])).hexdigest()
                                  for p in parts})

    def test_image_data_urls_are_collected_and_remote_urls_are_not(self):
        png = b"\x89PNG\r\n\x1a\nfake"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": {"url": _data_url("image/png", png)}},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                    {"type": "input_image", "image_url": _data_url("image/jpeg", b"jpeg-bytes")},
                    {"type": "input_file", "filename": "Memo.TXT", "file_data": _data_url("text/plain", b"memo")},
                ],
            }
        ]

        files = collect_inline_files(messages)

        assert [(f.filename, f.mime_type) for f in files] == [
            ("image-1.png", "image/png"),
            ("image-2.jpg", "image/jpeg"),
            ("Memo.txt", "text/plain"),
        ]
        assert files[0].data == png

    def test_assistant_and_system_messages_are_ignored(self):
        part = {"type": "file", "file": {"filename": "a.pdf", "file_data": _data_url("application/pdf", b"%PDF")}}
        assert collect_inline_files([{"role": "assistant", "content": [part]}]) == []

    def test_a_file_id_part_is_left_alone(self):
        messages = [{"role": "user", "content": [{"type": "file", "file": {"file_id": "file-abc"}}]}]
        assert collect_inline_files(messages) == []


class TestTranslate:
    def test_the_request_carries_the_files_and_leaves_the_client_messages_alone(self, scenario_dir: Path):
        body = v1.build_requests("V1-03", scenario_dir, payload="file_parts")[0]["body"]
        snapshot = copy.deepcopy(body)

        internal = translate_request(body, "key")

        assert body == snapshot
        assert len(internal["inline_files"]) == 4

    def test_a_continuation_carries_the_replayed_files(self, scenario_dir: Path):
        body = v1.build_requests("V1-03", scenario_dir, payload="file_parts")[-1]["body"]
        internal = translate_request(body, "key")
        assert internal["tool_actions"]
        assert len(internal["inline_files"]) == 4

    def test_plain_text_requests_carry_no_files(self, scenario_dir: Path):
        body = v1.build_requests("V1-01", scenario_dir, payload="text")[0]["body"]
        assert "inline_files" not in translate_request(body, "key")


class TestApplyConverted:
    def _internal(self, scenario_dir: Path, step: int = 0) -> Dict[str, Any]:
        body = v1.build_requests("V1-03", scenario_dir, payload="file_parts")[step]["body"]
        return translate_request(body, "key")

    def test_converted_parts_leave_the_turn_and_become_attachment_ids(self, scenario_dir: Path):
        internal = self._internal(scenario_dir)
        files = internal.pop("inline_files")
        converted = {f.content_hash: f"att-{i}" for i, f in enumerate(files)}

        apply_converted_files(internal, files, converted)

        assert internal["attachments"] == [f"att-{i}" for i in range(4)]
        # Only text was left, so the turn is a plain question again.
        assert "multimodal_content" not in internal
        assert internal["question"]

    def test_a_file_that_was_not_converted_stays_in_the_turn(self, scenario_dir: Path):
        internal = self._internal(scenario_dir)
        files = internal.pop("inline_files")
        converted = {files[0].content_hash: "att-0"}

        apply_converted_files(internal, files, converted)

        kept = [p for p in internal["multimodal_content"] if p.get("type") == "file"]
        assert len(kept) == 3
        assert internal["attachments"] == ["att-0"]

    def test_explicit_attachment_ids_are_kept(self, scenario_dir: Path):
        internal = self._internal(scenario_dir)
        internal["attachments"] = ["explicit"]
        files = internal.pop("inline_files")

        apply_converted_files(internal, files, {files[0].content_hash: "att-0"})

        assert internal["attachments"] == ["att-0", "explicit"]

    def test_a_continuation_replays_the_messages_without_the_converted_parts(self, scenario_dir: Path):
        body = v1.build_requests("V1-03", scenario_dir, payload="file_parts")[-1]["body"]
        snapshot = copy.deepcopy(body)
        internal = translate_request(body, "key")
        files = internal.pop("inline_files")

        apply_converted_files(internal, files, {f.content_hash: f"att-{i}" for i, f in enumerate(files)})

        user = internal["messages"][1]
        parts = user["content"] if isinstance(user["content"], list) else [{"type": "text"}]
        assert not any(p.get("type") == "file" for p in parts)
        assert internal["attachments"] == [f"att-{i}" for i in range(4)]
        assert body == snapshot
