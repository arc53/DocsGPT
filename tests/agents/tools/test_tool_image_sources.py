"""Tools that hand the model images: view_image, code_executor charts, read_webpage links."""

import base64
import io
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch

import pytest
from PIL import Image

from docsgpt.agents.tools import view_image as view
from docsgpt.agents.tools.read_webpage import ReadWebpageTool
from docsgpt.sandbox.base import ExecResult, Plot

pytestmark = pytest.mark.unit


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "green").save(out, "PNG")
    return out.getvalue()


class _Response:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        pass


class TestAddViewImageTool:
    def test_added_beside_a_tool_that_points_to_images(self):
        tools = {"t1": {"name": "code_executor", "actions": []}}
        assert view.add_view_image_tool(tools) is True
        entry = tools[view.VIEW_IMAGE_TOOL_ID]
        assert entry["id"] == "view_image" and entry["actions"][0]["name"] == "view_image"

    def test_not_added_without_one(self):
        tools = {"t1": {"name": "brave", "actions": []}}
        assert view.add_view_image_tool(tools) is False and tools.keys() == {"t1"}

    def test_a_client_tool_keeps_the_name(self):
        tools = {"t1": {"name": "read_webpage", "actions": []},
                 "ct0": {"name": "view_image", "client_side": True, "actions": [{"name": "view_image"}]}}
        assert view.add_view_image_tool(tools) is False

    def test_the_agent_adds_it_only_for_a_vision_model(self):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent.__new__(ClassicAgent)
        agent.tool_executor = MagicMock()
        agent._compute_turn_capabilities = Mock()
        agent._sync_attachments_tool = Mock()
        agent._llm_supports_tools = Mock(return_value=True)
        agent.llm = Mock()
        for types, expected in (([], False), (["image/png"], True)):
            agent.llm.get_supported_attachment_types = Mock(return_value=types)
            tools = {"t1": {"name": "code_executor", "actions": []}}
            agent._prepare_tools(tools)
            assert ("view_image" in tools) is expected


@contextmanager
def _artifacts(version):
    repo = Mock()
    repo.get_artifact_in_parent = Mock(return_value={"id": "a-1", "current_version": 1, "title": "t"})
    repo.get_version = Mock(return_value=version)
    with patch.object(view, "db_readonly"), patch.object(view, "ArtifactsRepository", return_value=repo), \
            patch.object(view, "resolve_artifact_id", return_value="a-1") as resolve:
        yield resolve


class TestViewImage:
    def test_an_image_artifact_is_queued_by_reference(self):
        tool = view.ViewImageTool({"workflow_run_id": "run-1"})
        version = {"mime_type": "image/png", "filename": "chart.png", "storage_path": "inputs/u/artifacts/a/v1/c.png"}
        with _artifacts(version) as resolve:
            result = tool.execute_action("view_image", source="a2")
        assert result == "Image A2 chart.png is shown with this result."
        assert resolve.call_args.kwargs == {"conversation_id": None, "workflow_run_id": "run-1"}
        assert tool.drain_native_parts() == [
            {"path": "inputs/u/artifacts/a/v1/c.png", "mime_type": "image/png", "label": "A2 chart.png"}
        ]

    def test_an_artifact_that_is_not_an_image(self):
        tool = view.ViewImageTool({"conversation_id": "c-1"})
        with _artifacts({"mime_type": "text/csv", "filename": "d.csv", "storage_path": "p"}):
            assert "is not an image (text/csv)" in tool.execute_action("view_image", source="A1")
        assert tool.drain_native_parts() == []

    def test_artifacts_need_a_conversation_or_run(self):
        assert "not available here" in view.ViewImageTool({}).execute_action("view_image", source="A1")

    @patch.object(view, "pinned_fetch_bytes")
    def test_a_web_image_is_fetched_and_queued(self, fetch):
        fetch.return_value = (_png(), _Response())
        tool = view.ViewImageTool({})
        result = tool.execute_action("view_image", source="https://x.test/a.png")
        assert "untrusted" in result
        (part,) = tool.drain_native_parts()
        assert part["label"] == "https://x.test/a.png" and part["mime_type"] == "image/png"
        assert base64.b64decode(part["data"]) == _png()
        assert fetch.call_args.kwargs["max_bytes"] == view.MAX_IMAGE_BYTES

    @pytest.mark.parametrize(
        "fetched, expected",
        [
            ((b"<html>", _Response()), "not an image that can be shown"),
            ((b"", _Response(302, {"Location": "https://x.test/b.png"})), "redirects to 'https://x.test/b.png'"),
            ((b"", _Response(404)), "returned HTTP 404"),
        ],
    )
    @patch.object(view, "pinned_fetch_bytes")
    def test_a_url_that_gives_no_image(self, fetch, fetched, expected):
        fetch.return_value = fetched
        tool = view.ViewImageTool({})
        assert expected in tool.execute_action("view_image", source="https://x.test/a.png")
        assert tool.drain_native_parts() == []

    @patch.object(view, "pinned_fetch_bytes", side_effect=view.UnsafeUserUrlError("private address"))
    def test_an_unsafe_url_is_refused(self, _fetch):
        assert "URL validation failed" in view.ViewImageTool({}).execute_action(
            "view_image", source="http://10.0.0.1/a.png"
        )

    def test_a_source_that_is_neither(self):
        assert "source must be" in view.ViewImageTool({}).execute_action("view_image", source="chart.png")


class TestCodeExecutorCharts:
    def _run(self, monkeypatch, plots, **kwargs):
        from docsgpt.agents.tools import code_executor as ce
        from tests.test_code_executor_tool import _FakeManager, _tool

        manager = _FakeManager(ExecResult(status="ok", stdout="ok", plots=plots))
        monkeypatch.setattr(ce.SandboxCreator, "get_manager", lambda: manager)
        persist = Mock(side_effect=lambda **kw: {"artifact_id": "art-1", "version": 1, "ref": "A3",
                                                 "filename": kw["filename"], "mime_type": kw["mime_type"]})
        monkeypatch.setattr(ce, "persist_new_artifact", persist)
        tool = _tool()
        return tool, persist, tool.execute_action("run_code", code="plt.show()", **kwargs)

    def test_a_displayed_chart_is_saved_and_shown(self, monkeypatch):
        png = base64.b64encode(_png()).decode()
        tool, persist, payload = self._run(monkeypatch, [Plot(format="png", content_base64=png)])

        filename = persist.call_args.kwargs["filename"]
        assert filename.startswith("chart-") and filename.endswith(".png")
        assert persist.call_args.kwargs["mime_type"] == "image/png"
        assert payload["artifacts"][0]["ref"] == "A3"
        assert payload["charts_shown"] == [f"A3 {filename}"]
        assert tool.get_artifacts("run_code")[0]["id"] == "art-1"
        (part,) = tool.drain_native_parts()
        assert part["label"] == f"A3 {filename}" and part["data"] == png

    def test_without_capture_the_chart_is_shown_but_not_saved(self, monkeypatch):
        png = base64.b64encode(_png()).decode()
        tool, persist, payload = self._run(monkeypatch, [Plot(format="png", content_base64=png)],
                                           capture_artifacts=False)
        persist.assert_not_called()
        assert payload["artifacts"] == [] and len(tool.drain_native_parts()) == 1

    def test_a_run_never_reports_an_earlier_runs_charts(self, monkeypatch):
        tool, _, _ = self._run(monkeypatch, [])
        tool._native_queue = [{"label": "stale"}]
        tool.execute_action("run_code", code="print(1)", capture_artifacts=False)
        assert tool.drain_native_parts() == []

    def test_no_charts_no_change(self, monkeypatch):
        tool, persist, payload = self._run(monkeypatch, [])
        assert "charts_shown" not in payload and tool.drain_native_parts() == []


class TestReadWebpageImageLinks:
    @patch("docsgpt.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_image_links_are_absolute_and_inline_images_dropped(self, fetch):
        html = (b'<p>Plan</p><img src="/img/plan.png" alt="plan">'
                b'<img src="data:image/png;base64,' + b"A" * 5000 + b'">')
        fetch.return_value = (html, _Response(headers={"Content-Type": "text/html"}))
        result = ReadWebpageTool().execute_action("read_webpage", url="https://ex.test/docs/page")
        assert "![plan](https://ex.test/img/plan.png)" in result
        assert "[inline image]" in result and "AAAA" not in result

    @patch("docsgpt.agents.tools.read_webpage.pinned_fetch_bytes")
    def test_an_image_url_points_to_view_image(self, fetch):
        fetch.return_value = (b"\x89PNG", _Response(headers={"Content-Type": "image/png"}))
        result = ReadWebpageTool().execute_action("read_webpage", url="https://ex.test/a.png")
        assert "view_image" in result and "image/png" in result
