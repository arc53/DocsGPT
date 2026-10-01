"""The attachment budget planner: what of a turn's files goes into the context."""

import pytest

from docsgpt.agents.attachment_budget import (
    MIN_PARTIAL_TOKENS,
    SPREADSHEET_PREVIEW_TOKENS,
    AttachmentPlan,
    FileStatus,
    compute_attachment_budget,
    plan_attachments,
)
from docsgpt.agents.turn_capabilities import TurnCapabilities

pytestmark = pytest.mark.unit


def caps(
    *,
    tool_calling=True,
    vision=False,
    native_pdf=False,
    sandbox=False,
    attachments_tool=False,
    window=262_144,
):
    types = []
    if vision:
        types += ["image/png", "image/jpeg"]
    if native_pdf:
        types.append("application/pdf")
    return TurnCapabilities(
        tool_calling=tool_calling,
        vision=vision,
        native_pdf=native_pdf,
        sandbox=sandbox,
        window=window,
        is_v1=False,
        attachments_tool=attachments_tool,
        sandbox_action="run_code" if sandbox else None,
        attachments_actions=("attachments_read",) if attachments_tool else (),
        supported_attachment_types=tuple(types),
    )


_counter = {"n": 0}


def att(
    name="doc.txt",
    tokens=1000,
    *,
    mime="text/plain",
    original=None,
    status="ok",
    content_hash=None,
    size=None,
    pages=None,
    content="x",
):
    _counter["n"] += 1
    metadata = {
        "extraction": {
            "status": status,
            "truncated": bool(original and original > tokens),
            "original_tokens": original if original is not None else tokens,
            "stored_tokens": tokens,
        }
    }
    if content_hash:
        metadata["content_hash"] = content_hash
    if pages is not None:
        metadata["page_count"] = pages
    return {
        "id": f"att-{_counter['n']}",
        "filename": name,
        "mime_type": mime,
        "token_count": tokens,
        "size": size,
        "content": content,
        "metadata": metadata,
    }


def statuses(plan: AttachmentPlan):
    return [f.status for f in plan.files]


class TestComputeBudget:
    def test_share_caps_the_budget(self):
        budget = compute_attachment_budget(window=100_000, share=0.5)
        assert budget == 50_000

    def test_free_space_caps_the_budget(self):
        budget = compute_attachment_budget(
            window=100_000, share=0.9, system_tokens=10_000, query_tokens=5_000
        )
        # 10% of the window is kept for the answer.
        assert budget == 100_000 - 10_000 - 10_000 - 5_000

    def test_post_compression_history_is_budgeted_against(self):
        without = compute_attachment_budget(window=100_000, share=0.9)
        with_history = compute_attachment_budget(window=100_000, share=0.9, history_tokens=30_000)
        assert without - with_history == 30_000

    def test_documents_reserve_is_bounded(self):
        budget = compute_attachment_budget(window=100_000, share=1.0, docs_tokens=90_000)
        # Retrieved documents are shed lowest-ranked first, so only a bounded
        # reserve is held back for them.
        assert budget > 50_000

    def test_never_negative(self):
        assert compute_attachment_budget(window=1000, share=0.5, system_tokens=5000) == 0


class TestWalk:
    def test_small_attachments_inline_whole_as_today(self):
        plan = plan_attachments([att("a.txt", 800), att("b.txt", 1200)], caps(), budget=100_000)
        assert statuses(plan) == [FileStatus.INLINE, FileStatus.INLINE]
        assert [f.ref for f in plan.files] == ["F1", "F2"]
        assert all(not f.native for f in plan.files)
        assert plan.files[0].shown_tokens == 800

    def test_incident_shape_first_whole_files_then_one_partial(self):
        files = [att(f"report_{i}.pdf", 28_000, mime="application/pdf") for i in range(46)]
        plan = plan_attachments(files, caps(attachments_tool=True), budget=131_072)

        got = statuses(plan)
        inline = got.count(FileStatus.INLINE)
        assert inline == 4
        assert got[:inline] == [FileStatus.INLINE] * inline
        assert got[inline] == FileStatus.PARTIAL
        assert set(got[inline + 1:]) == {FileStatus.TOOL}
        assert plan.inline_tokens <= 131_072
        partial = plan.files[inline]
        assert MIN_PARTIAL_TOKENS <= partial.shown_tokens < partial.text_tokens

    def test_overflow_without_the_attachments_tool_is_not_included(self):
        files = [att(f"r{i}.txt", 40_000) for i in range(5)]
        plan = plan_attachments(files, caps(attachments_tool=False), budget=90_000)
        assert FileStatus.NOT_INCLUDED in statuses(plan)
        assert FileStatus.TOOL not in statuses(plan)

    def test_no_tool_calling_overflow_is_not_included(self):
        files = [att(f"r{i}.txt", 40_000) for i in range(5)]
        plan = plan_attachments(files, caps(tool_calling=False), budget=90_000)
        assert statuses(plan)[-1] == FileStatus.NOT_INCLUDED

    def test_back_fill_after_a_file_that_does_not_fit(self):
        files = [att("small1.txt", 2_000), att("huge.txt", 90_000), att("small2.txt", 3_000)]
        plan = plan_attachments(files, caps(), budget=40_000)
        assert statuses(plan) == [FileStatus.INLINE, FileStatus.PARTIAL, FileStatus.INLINE]
        huge = plan.files[1]
        # The partial gets what the back-filled files left over.
        assert huge.shown_tokens < 40_000 - 5_000
        assert plan.inline_tokens <= 40_000

    def test_partial_needs_a_minimum_remaining_budget(self):
        files = [att("a.txt", 9_000), att("huge.txt", 90_000)]
        plan = plan_attachments(files, caps(), budget=9_000 + MIN_PARTIAL_TOKENS - 500)
        assert statuses(plan) == [FileStatus.INLINE, FileStatus.NOT_INCLUDED]

    def test_only_one_partial(self):
        files = [att("big1.txt", 90_000), att("big2.txt", 90_000)]
        plan = plan_attachments(files, caps(attachments_tool=True), budget=60_000)
        assert statuses(plan) == [FileStatus.PARTIAL, FileStatus.TOOL]


class TestNativeParts:
    def test_native_pdf_uses_original_tokens(self):
        pdf = att("long.pdf", 100_000, mime="application/pdf", original=180_000, pages=100)
        plan = plan_attachments([pdf], caps(native_pdf=True), budget=250_000)
        assert plan.files[0].native is True
        assert plan.files[0].inline_tokens >= 180_000

    def test_text_only_model_uses_stored_tokens(self):
        pdf = att("long.pdf", 100_000, mime="application/pdf", original=180_000)
        plan = plan_attachments([pdf], caps(), budget=250_000)
        assert plan.files[0].native is False
        assert 100_000 <= plan.files[0].inline_tokens < 101_000

    def test_native_part_is_never_partial_falls_back_to_text(self):
        pdf = att("long.pdf", 60_000, mime="application/pdf", original=60_000, pages=200)
        plan = plan_attachments([pdf], caps(native_pdf=True), budget=30_000)
        file = plan.files[0]
        assert file.status == FileStatus.PARTIAL
        assert file.native is False

    def test_scan_too_big_for_native_and_without_text_is_not_partial(self):
        scan = att(
            "scan.pdf", 0, mime="application/pdf", status="no_text", content="", pages=400
        )
        plan = plan_attachments([scan], caps(native_pdf=True), budget=50_000)
        assert plan.files[0].status == FileStatus.NOT_INCLUDED
        assert plan.files[0].shown_tokens == 0

    def test_images_go_native_on_vision_models(self):
        plan = plan_attachments([att("a.png", 0, mime="image/png", content="")], caps(vision=True), budget=50_000)
        assert plan.files[0].status == FileStatus.INLINE
        assert plan.files[0].native is True
        assert plan.native_tokens > 0

    def test_native_cap_is_respected(self):
        images = [att(f"s{i}.png", 0, mime="image/png", content="") for i in range(12)]
        plan = plan_attachments(images, caps(vision=True), budget=200_000, max_native_parts=10)
        assert statuses(plan).count(FileStatus.INLINE) == 10
        assert plan.native_parts == 10
        assert plan.files[-1].status == FileStatus.NOT_INCLUDED
        assert plan.files[-1].reason == "native_cap"

    def test_native_cap_falls_back_to_text_when_there_is_text(self):
        images = [att(f"s{i}.png", 50, mime="image/png", content="ocr text") for i in range(3)]
        plan = plan_attachments(images, caps(vision=True), budget=200_000, max_native_parts=2)
        assert [f.native for f in plan.files] == [True, True, False]
        assert plan.files[2].status == FileStatus.INLINE

    def test_synthetic_pdf_pages_count_as_image_parts(self):
        pdf = att("deck.pdf", 900, mime="application/pdf", pages=3)
        plan = plan_attachments([pdf], caps(vision=True), budget=50_000)
        file = plan.files[0]
        assert file.native is True
        assert file.native_parts == 3


class TestUnreadable:
    def test_failed_extraction(self):
        plan = plan_attachments([att("x.docx", 0, status="failed", content=None)], caps(), budget=10_000)
        assert plan.files[0].status == FileStatus.UNREADABLE

    def test_image_on_a_text_only_model(self):
        plan = plan_attachments([att("a.png", 0, mime="image/png", content="")], caps(), budget=10_000)
        assert plan.files[0].status == FileStatus.UNREADABLE

    def test_image_with_ocr_text_on_a_text_only_model_is_text(self):
        plan = plan_attachments([att("a.png", 20, mime="image/png", content="Total 42")], caps(), budget=10_000)
        assert plan.files[0].status == FileStatus.INLINE
        assert plan.files[0].native is False

    def test_scan_on_a_text_only_model(self):
        scan = att("scan.pdf", 0, mime="application/pdf", status="no_text", content="")
        plan = plan_attachments([scan], caps(), budget=10_000)
        assert plan.files[0].status == FileStatus.UNREADABLE


class TestDedupeAndRefs:
    def test_same_hash_collapses_to_one_ref(self):
        a = att("a.pdf", 500, content_hash="h1")
        b = att("a (1).pdf", 500, content_hash="h1")
        c = att("c.pdf", 500, content_hash="h2")
        plan = plan_attachments([a, b, c], caps(), budget=50_000)
        assert [f.ref for f in plan.files] == ["F1", "F2"]
        assert plan.files[0].attachment_ids == (a["id"], b["id"])
        assert plan.for_attachment(b["id"]).ref == "F1"
        assert plan.inline_tokens < 2 * 600

    def test_hash_column_collapses_like_the_metadata_hash(self):
        """Rows read after migration 0044 carry the hash as a column."""
        a = att("a.pdf", 500)
        a["content_hash"] = "h1"
        b = att("b.pdf", 500, content_hash="h1")
        plan = plan_attachments([a, b], caps(), budget=50_000)
        assert [f.attachment_ids for f in plan.files] == [(a["id"], b["id"])]

    def test_filename_and_size_fallback(self):
        a = att("same.txt", 500, size=1234)
        b = att("same.txt", 500, size=1234)
        c = att("same.txt", 500)  # unknown size never collapses
        d = att("same.txt", 500)
        plan = plan_attachments([a, b, c, d], caps(), budget=50_000)
        assert len(plan.files) == 3

    def test_refs_follow_upload_order_across_the_conversation(self):
        earlier = [att("old1.txt", 500), att("old2.txt", 500)]
        current = [att("new.txt", 500)]
        plan = plan_attachments(current, caps(), budget=50_000, earlier=earlier)
        assert [(f.ref, f.filename, f.status) for f in plan.files] == [
            ("F1", "old1.txt", FileStatus.EARLIER),
            ("F2", "old2.txt", FileStatus.EARLIER),
            ("F3", "new.txt", FileStatus.INLINE),
        ]
        assert plan.inline_tokens < 600 + 500

    def test_earlier_images_are_never_resent(self):
        earlier = [att("shot.png", 0, mime="image/png", content="")]
        plan = plan_attachments([], caps(vision=True), budget=50_000, earlier=earlier)
        assert plan.files[0].status == FileStatus.EARLIER
        assert plan.native_parts == 0
        assert plan.inline_tokens == 0

    def test_reattached_earlier_file_stays_earlier_when_the_tool_can_read_it(self):
        old = att("contract.pdf", 5_000, content_hash="h")
        again = att("contract.pdf", 5_000, content_hash="h")
        plan = plan_attachments([again], caps(attachments_tool=True), budget=50_000, earlier=[old])
        assert len(plan.files) == 1
        assert plan.files[0].status == FileStatus.EARLIER
        assert plan.inline_tokens == 0

    def test_reattached_earlier_file_inlines_when_nothing_else_can_reach_it(self):
        old = att("contract.pdf", 5_000, content_hash="h")
        again = att("contract.pdf", 5_000, content_hash="h")
        plan = plan_attachments([again], caps(), budget=50_000, earlier=[old])
        assert len(plan.files) == 1
        assert plan.files[0].ref == "F1"
        assert plan.files[0].status == FileStatus.INLINE
        assert plan.for_attachment(again["id"]) is plan.files[0]


class TestSandbox:
    def test_spreadsheets_get_a_preview_when_the_sandbox_is_there(self):
        sheet = att("data.xlsx", 50_000, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        plan = plan_attachments([sheet], caps(sandbox=True), budget=200_000)
        file = plan.files[0]
        assert file.status == FileStatus.SANDBOX
        assert 0 < file.shown_tokens <= SPREADSHEET_PREVIEW_TOKENS

    def test_csv_detected_by_extension(self):
        sheet = att("rows.csv", 50_000, mime="application/octet-stream")
        plan = plan_attachments([sheet], caps(sandbox=True), budget=200_000)
        assert plan.files[0].status == FileStatus.SANDBOX

    def test_without_sandbox_spreadsheets_inline_as_text(self):
        sheet = att("rows.csv", 5_000, mime="text/csv")
        plan = plan_attachments([sheet], caps(), budget=200_000)
        assert plan.files[0].status == FileStatus.INLINE

    def test_oversized_spreadsheet_is_not_sent_to_the_sandbox(self):
        sheet = att("rows.csv", 5_000, mime="text/csv", size=10**12)
        plan = plan_attachments([sheet], caps(sandbox=True), budget=200_000)
        assert plan.files[0].status == FileStatus.INLINE


class TestTotals:
    def test_inline_tokens_sum_what_is_spent(self):
        files = [att("a.txt", 1_000), att("b.png", 0, mime="image/png", content="")]
        plan = plan_attachments(files, caps(vision=True), budget=100_000)
        assert plan.inline_tokens == sum(f.inline_tokens for f in plan.files)
        assert plan.native_tokens == plan.files[1].inline_tokens
        assert plan.reserved_tokens > plan.inline_tokens
        assert plan.reserved_tokens <= 100_000

    def test_empty_plan(self):
        plan = plan_attachments([], caps(), budget=100_000)
        assert plan.files == []
        assert plan.reserved_tokens == 0


class TestSettings:
    def test_defaults(self):
        from docsgpt.core.settings import settings

        assert settings.ATTACHMENT_BUDGET_SHARE == 0.5
        assert settings.ATTACHMENT_MAX_NATIVE_PARTS == 40


class TestEarlierRowsWithoutText:
    def test_reattached_copy_brings_the_text(self):
        # Earlier-turn rows are loaded without their content; a re-sent copy
        # inlined under the first ref must use the copy that has it.
        old = att("contract.pdf", 5_000, content_hash="h")
        old.pop("content")
        again = att("contract.pdf", 5_000, content_hash="h", content="the text")
        plan = plan_attachments([again], caps(), budget=50_000, earlier=[old])
        assert plan.files[0].status == FileStatus.INLINE
        assert plan.files[0].attachment is again
