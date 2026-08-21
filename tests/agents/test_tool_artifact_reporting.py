"""A tool call must report every artifact it produced, with display names.

``get_artifact_id`` returns one id, so a single ``run_code`` that wrote two
files surfaced only the first — the second existed in the database and was
downloadable by API, but had no button in the UI and no way to reach it. The
one button it did render was labelled with the tool's name ("Code Executor"),
which says nothing about which file it opens.
"""

from __future__ import annotations

import pytest

from application.agents.tools.artifact_generator import ArtifactGeneratorTool
from application.agents.tools.code_executor import CodeExecutorTool


@pytest.mark.unit
class TestCodeExecutorArtifacts:
    def test_reports_every_captured_file(self):
        tool = CodeExecutorTool({})
        tool._last_artifacts = [
            {"id": "a1", "filename": "nda.pdf"},
            {"id": "a2", "filename": "saas.pdf"},
        ]
        assert tool.get_artifacts("run_code") == [
            {"id": "a1", "filename": "nda.pdf"},
            {"id": "a2", "filename": "saas.pdf"},
        ]

    def test_primary_id_still_reported_for_back_compat(self):
        tool = CodeExecutorTool({})
        tool._last_artifact_id = "a1"
        assert tool.get_artifact_id("run_code") == "a1"

    def test_no_artifacts_is_empty_not_none(self):
        assert CodeExecutorTool({}).get_artifacts("run_code") == []

    def test_returned_list_is_a_copy(self):
        """A caller mutating the result must not corrupt the tool's state."""
        tool = CodeExecutorTool({})
        tool._last_artifacts = [{"id": "a1", "filename": "nda.pdf"}]
        tool.get_artifacts("run_code").clear()
        assert tool._last_artifacts == [{"id": "a1", "filename": "nda.pdf"}]


@pytest.mark.unit
class TestArtifactGeneratorArtifacts:
    def test_carries_the_rendered_filename_and_ref(self):
        """``ref`` travels with the artifact so the UI can resolve ``A1``.

        The model announces a file by its ref; without this the UI could only
        guess which artifact ``A1`` meant, and a conversation-scoped ref
        resolved positionally within one turn opens the wrong file.
        """
        tool = ArtifactGeneratorTool({})
        tool._last_artifact_id = "b1"
        tool._last_filename = "Mock_SaaS_Agreement.pdf"
        tool._last_ref = "A2"
        assert tool.get_artifacts("create_artifact") == [
            {"id": "b1", "filename": "Mock_SaaS_Agreement.pdf", "ref": "A2"}
        ]

    def test_nothing_produced_is_empty(self):
        tool = ArtifactGeneratorTool({})
        tool._last_artifact_id = None
        assert tool.get_artifacts("create_artifact") == []


@pytest.mark.unit
class TestExecutorRecordsArtifacts:
    """The executor must tolerate a tool returning an unexpected shape."""

    @staticmethod
    def _extract(produced):
        """Mirror the executor's normalization step."""
        return [
            {"id": str(a["id"]).strip(), "filename": a.get("filename")}
            for a in (produced or [])
            if isinstance(a, dict) and a.get("id")
        ]

    def test_drops_entries_without_an_id(self):
        assert self._extract([{"filename": "x.pdf"}, {"id": "a1"}]) == [
            {"id": "a1", "filename": None}
        ]

    def test_ignores_non_dict_entries(self):
        assert self._extract(["nope", 42, {"id": "a1", "filename": "x.pdf"}]) == [
            {"id": "a1", "filename": "x.pdf"}
        ]

    def test_none_is_empty(self):
        assert self._extract(None) == []
