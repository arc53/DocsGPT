"""Reading the marker a scheduled run's answer opens with when the agent cannot do its task."""

import pytest

from docsgpt.agents.cannot_complete import cannot_complete_reason, drop_cannot_complete_marker


@pytest.mark.unit
class TestCannotCompleteReason:
    @pytest.mark.parametrize(
        "answer",
        [
            "CANNOT_COMPLETE: no browser tool to open the site",
            "  \n\nCANNOT_COMPLETE: no browser tool to open the site",
            "**CANNOT_COMPLETE:** no browser tool to open the site",
            "**CANNOT_COMPLETE**: no browser tool to open the site",
            "**CANNOT_COMPLETE: no browser tool to open the site**",
            "## CANNOT_COMPLETE: no browser tool to open the site",
            "cannot_complete: no browser tool to open the site",
            "Cannot complete: no browser tool to open the site",
            "CANNOT\\_COMPLETE: no browser tool to open the site",
            "`CANNOT_COMPLETE:` no browser tool to open the site",
        ],
    )
    def test_the_marker_at_the_start_gives_its_reason(self, answer):
        assert cannot_complete_reason(answer) == "no browser tool to open the site"

    def test_only_the_reason_line_is_taken(self):
        answer = "CANNOT_COMPLETE: Step 2 (send the email): no email tool.\n\nThe site itself is up."

        assert cannot_complete_reason(answer) == "Step 2 (send the email): no email tool."

    def test_a_reason_on_the_next_line_is_found(self):
        assert cannot_complete_reason("**CANNOT_COMPLETE:**\n\nNo email tool.") == "No email tool."

    def test_a_marker_with_no_reason_still_counts(self):
        assert cannot_complete_reason("CANNOT_COMPLETE:")

    def test_a_long_reason_is_capped(self):
        assert len(cannot_complete_reason("CANNOT_COMPLETE: " + "x" * 2000)) == 500

    @pytest.mark.parametrize(
        "answer",
        [
            "",
            None,
            "The site is up. I cannot complete the second check without a login, so I skipped it.",
            "I cannot complete: the page needs a login.",
            "Cannot complete the request because the page needs a login.",
            "All checks passed.\n\nCANNOT_COMPLETE: no email tool",
            "Cannot be completed: no login",
        ],
    )
    def test_anything_else_is_an_ordinary_answer(self, answer):
        assert cannot_complete_reason(answer) is None


@pytest.mark.unit
class TestDropCannotCompleteMarker:
    def test_the_marker_line_reads_as_its_reason(self):
        answer = "**CANNOT_COMPLETE:** Step 2 (send the email): no email tool.\n\nThe site itself is up."

        assert drop_cannot_complete_marker(answer) == "Step 2 (send the email): no email tool.\n\nThe site itself is up."

    def test_a_marker_further_down_is_dropped_too(self):
        answer = "Prices fetched.\n\nCANNOT_COMPLETE: no email tool to send them"

        assert drop_cannot_complete_marker(answer) == "Prices fetched.\n\nno email tool to send them"

    def test_a_bare_marker_line_goes(self):
        assert drop_cannot_complete_marker("CANNOT_COMPLETE:\nNo email tool.") == "No email tool."
