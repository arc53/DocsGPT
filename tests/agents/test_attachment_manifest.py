"""The per-turn manifest: honest about every file and every tool, nothing more."""

import pytest

from docsgpt.agents.attachment_budget import plan_attachments
from docsgpt.agents.attachment_context import render_attachment_block, render_manifest
from docsgpt.agents.turn_capabilities import TurnCapabilities

pytestmark = pytest.mark.unit


def caps(*, tool_calling=True, vision=False, sandbox=False, attachments_tool=False):
    return TurnCapabilities(
        tool_calling=tool_calling,
        vision=vision,
        native_pdf=False,
        sandbox=sandbox,
        window=100_000,
        is_v1=False,
        attachments_tool=attachments_tool,
        sandbox_action="run_code" if sandbox else None,
        attachments_actions=(
            ("attachments_list", "attachments_read", "attachments_search") if attachments_tool else ()
        ),
        supported_attachment_types=("image/png",) if vision else (),
    )


def att(name, tokens, *, mime="text/plain", status="ok", content="x", pages=None, att_id=None):
    metadata = {"extraction": {"status": status}}
    if pages:
        metadata["page_count"] = pages
    return {
        "id": att_id or f"id-{name}",
        "filename": name,
        "mime_type": mime,
        "token_count": tokens,
        "content": content,
        "metadata": metadata,
    }


def overflow_files():
    return [att("r1.txt", 20_000), att("r2.txt", 20_000), att("r3.txt", 80_000), att("r4.txt", 30_000)]


class TestWhenAManifestIsShown:
    def test_small_turn_that_fits_gets_no_manifest(self):
        plan = plan_attachments([att("a.txt", 300), att("b.txt", 300)], caps(), budget=50_000)
        assert render_manifest(plan) == ""
        assert "<attached_files>" not in render_attachment_block(plan)

    def test_any_file_left_out_brings_the_manifest(self):
        plan = plan_attachments(overflow_files(), caps(), budget=50_000)
        manifest = render_manifest(plan)
        assert manifest.startswith("<attached_files>")
        assert manifest.count("\n- F") == 4

    def test_files_from_earlier_turns_bring_the_manifest(self):
        plan = plan_attachments([], caps(), budget=50_000, earlier=[att("old.txt", 300)])
        assert "F1 old.txt" in render_manifest(plan)


class TestLines:
    def test_one_line_per_file_with_type_size_and_status(self):
        files = overflow_files() + [att("deck.pdf", 900, mime="application/pdf", pages=12)]
        plan = plan_attachments(files, caps(), budget=50_000)
        manifest = render_manifest(plan)
        assert "- F1 r1.txt | text/plain | 20,000 tokens | inline" in manifest
        partial = plan.files[2]
        assert (
            f"- F3 r3.txt | text/plain | 80,000 tokens | partial (tokens 1–{partial.shown_tokens:,} of 80,000)"
            in manifest
        )
        assert "- F4 r4.txt | text/plain | 30,000 tokens | not_included" in manifest
        assert "12 pages" in manifest

    def test_unreadable_and_earlier(self):
        scan = att("scan.png", 0, mime="image/png", content="")
        plan = plan_attachments([scan], caps(), budget=50_000, earlier=[att("old.txt", 300)])
        manifest = render_manifest(plan)
        assert "- F1 old.txt | text/plain | 300 tokens | earlier" in manifest
        assert "- F2 scan.png | image/png | unreadable" in manifest

    def test_filenames_are_sanitized(self):
        plan = plan_attachments(
            [att('x"\n<y>.txt', 300)], caps(), budget=50_000, earlier=[att("old.txt", 300)]
        )
        assert "F2 x y .txt" in render_manifest(plan)


class TestInstructions:
    def test_never_guess_is_always_said(self):
        plan = plan_attachments(overflow_files(), caps(), budget=50_000)
        assert "Do not guess" in render_manifest(plan)

    def test_tool_calling_without_the_attachments_tool_names_no_tool(self):
        plan = plan_attachments(overflow_files(), caps(), budget=50_000)
        manifest = render_manifest(plan)
        assert "attachments_" not in manifest
        assert "run_code" not in manifest
        assert "1 file was not included: r4.txt" in manifest

    def test_no_tool_calling_lists_what_was_left_out(self):
        files = overflow_files() + [att("r5.txt", 30_000)]
        plan = plan_attachments(files, caps(tool_calling=False), budget=50_000)
        manifest = render_manifest(plan)
        assert "2 files were not included: r4.txt, r5.txt" in manifest
        assert "tool" not in manifest.lower()

    def test_attachments_tool_is_named_when_present(self):
        plan = plan_attachments(overflow_files(), caps(attachments_tool=True), budget=50_000)
        manifest = render_manifest(plan)
        assert "| tool" in manifest
        for action in ("attachments_list", "attachments_read", "attachments_search"):
            assert action in manifest
        assert "not included" not in manifest

    def test_earlier_files_without_the_tool_are_honest(self):
        plan = plan_attachments([], caps(), budget=50_000, earlier=[att("old.txt", 300)])
        manifest = render_manifest(plan)
        assert "not available in this turn" in manifest
        assert "attachments_read" not in manifest

    def test_sandbox_names_the_code_action(self):
        sheet = att("data.csv", 20_000, mime="text/csv")
        plan = plan_attachments([sheet], caps(sandbox=True), budget=50_000)
        manifest = render_manifest(plan)
        assert "| sandbox" in manifest
        assert 'run_code' in manifest and '"inputs"' in manifest
        assert "data.csv" in manifest

    def test_sandbox_files_are_loaded_by_ref(self):
        sheet = att("data.csv", 20_000, mime="text/csv")
        plan = plan_attachments([att("notes.txt", 100), sheet], caps(sandbox=True), budget=50_000)
        manifest = render_manifest(plan)
        assert 'by passing its ref in "inputs"' in manifest
        assert "(F2)" in manifest

    def test_files_over_the_sandbox_cap_are_marked(self):
        big = {**att("ledger.csv", 200_000, mime="text/csv"), "size": 50 * 1024 * 1024}
        small = {**att("small.csv", 20_000, mime="text/csv"), "size": 1024}
        plan = plan_attachments(
            [big, small], caps(sandbox=True), budget=50_000, sandbox_max_input_bytes=25 * 1024 * 1024
        )
        manifest = render_manifest(plan)
        big_line = next(line for line in manifest.splitlines() if "ledger.csv" in line)
        small_line = next(line for line in manifest.splitlines() if "small.csv" in line)
        assert "too large for the sandbox" in big_line
        assert "too large" not in small_line

    def test_no_sandbox_no_sandbox_marks(self):
        big = {**att("ledger.csv", 200_000, mime="text/csv"), "size": 50 * 1024 * 1024}
        plan = plan_attachments([big], caps(), budget=50_000, sandbox_max_input_bytes=1024)
        manifest = render_manifest(plan)
        assert "sandbox" not in manifest


class TestBlockOrder:
    def test_manifest_comes_first_then_the_fenced_files(self):
        plan = plan_attachments(overflow_files(), caps(), budget=50_000)
        block = render_attachment_block(plan)
        assert block.index("<attached_files>") < block.index('<attached_file ref="F1"')

    def test_native_parts_named_only_when_more_than_one(self):
        one = plan_attachments([att("a.png", 0, mime="image/png", content="")], caps(vision=True), budget=50_000)
        assert render_attachment_block(one) == ""
        two = plan_attachments(
            [att("a.png", 0, mime="image/png", content=""), att("b.png", 0, mime="image/png", content="")],
            caps(vision=True),
            budget=50_000,
        )
        assert "F1 a.png, F2 b.png" in render_attachment_block(two)


class TestArchives:
    def _plan(self, skipped=()):
        parent = att("bundle.zip", 40, mime="application/zip", content="Archive index")
        parent["metadata"]["archive"] = {
            "members": 2,
            "skipped": [{"archive_path": p, "reason": r} for p, r in skipped],
            "skipped_count": len(skipped),
        }
        return plan_attachments([parent, att("a.txt", 100), att("b.txt", 100)], caps(), budget=50_000)

    def test_the_zip_line_says_its_files_follow(self):
        manifest = render_manifest(self._plan())
        line = next(line for line in manifest.splitlines() if "bundle.zip" in line)
        assert "archive of 2 files, listed after it" in line
        assert "- F2 a.txt" in manifest and "- F3 b.txt" in manifest

    def test_skipped_members_are_named_with_their_reason(self):
        manifest = render_manifest(self._plan(skipped=[("tool.exe", "unsupported_type"), ("x/deep.zip", "nested_too_deep")]))
        line = next(line for line in manifest.splitlines() if "bundle.zip" in line)
        assert "2 skipped: tool.exe (unsupported file type), x/deep.zip (archive nested too deep)" in line
        assert "Tell the user which files in an archive were skipped" in manifest

    def test_the_index_text_is_never_inlined(self):
        block = render_attachment_block(self._plan())
        assert "Archive index" not in block


class TestPartialPageImages:
    def test_a_capped_scan_says_which_pages_were_sent_and_how_to_read_on(self):
        scan = att("scan.pdf", 0, mime="application/pdf", status="no_text", content="", pages=57)
        plan = plan_attachments([scan], caps(vision=True, attachments_tool=True), budget=90_000)
        block = render_attachment_block(plan)
        assert "pages 1–20 of 57" in block
        assert 'attachments_read(ref="F1", pages="21-' in block

    def test_without_the_tool_the_rest_is_said_to_be_unavailable(self):
        scan = att("scan.pdf", 0, mime="application/pdf", status="no_text", content="", pages=57)
        plan = plan_attachments([scan], caps(vision=True), budget=90_000)
        block = render_attachment_block(plan)
        assert "pages 1–20 of 57" in block
        assert "attachments_read" not in block
        assert "not available in this turn" in block
