from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from application.templates.namespaces import (
    NamespaceBuilder,
    NamespaceManager,
    PassthroughNamespace,
    SourceNamespace,
    SystemNamespace,
    ToolsNamespace,
)


# ── SystemNamespace ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSystemNamespace:
    def test_namespace_name(self):
        ns = SystemNamespace()
        assert ns.namespace_name == "system"

    def test_build_returns_expected_keys(self):
        ns = SystemNamespace()
        result = ns.build()
        assert "date" in result
        assert "time" in result
        assert "timestamp" in result
        assert "request_id" in result
        assert "user_id" in result

    def test_build_with_request_id(self):
        ns = SystemNamespace()
        result = ns.build(request_id="req-123")
        assert result["request_id"] == "req-123"

    def test_build_with_user_id(self):
        ns = SystemNamespace()
        result = ns.build(user_id="user-456")
        assert result["user_id"] == "user-456"

    def test_build_generates_uuid_when_no_request_id(self):
        ns = SystemNamespace()
        result = ns.build()
        assert len(result["request_id"]) == 36  # UUID format

    def test_user_id_defaults_to_none(self):
        ns = SystemNamespace()
        result = ns.build()
        assert result["user_id"] is None

    def test_date_format(self):
        ns = SystemNamespace()
        fixed = datetime(2026, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        with patch("application.templates.namespaces.datetime") as mock_dt:
            mock_dt.now.return_value = fixed
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = ns.build()
        assert result["date"] == "2026-01-15"
        assert result["time"] == "10:30:45"

    def test_extra_kwargs_ignored(self):
        ns = SystemNamespace()
        result = ns.build(unknown_param="whatever")
        assert "date" in result


# ── PassthroughNamespace ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestPassthroughNamespace:
    def test_namespace_name(self):
        ns = PassthroughNamespace()
        assert ns.namespace_name == "passthrough"

    def test_none_data_returns_empty(self):
        ns = PassthroughNamespace()
        assert ns.build(passthrough_data=None) == {}

    def test_no_data_returns_empty(self):
        ns = PassthroughNamespace()
        assert ns.build() == {}

    def test_safe_types_pass_through(self):
        ns = PassthroughNamespace()
        data = {"s": "string", "i": 42, "f": 3.14, "b": True, "n": None}
        result = ns.build(passthrough_data=data)
        assert result == data

    def test_non_serializable_types_filtered(self):
        ns = PassthroughNamespace()
        data = {"good": "ok", "bad": object()}
        result = ns.build(passthrough_data=data)
        assert result == {"good": "ok"}

    def test_list_value_filtered(self):
        ns = PassthroughNamespace()
        data = {"list_val": [1, 2, 3]}
        result = ns.build(passthrough_data=data)
        assert result == {}

    def test_dict_value_filtered(self):
        ns = PassthroughNamespace()
        data = {"nested": {"key": "val"}}
        result = ns.build(passthrough_data=data)
        assert result == {}


# ── SourceNamespace ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSourceNamespace:
    def test_namespace_name(self):
        ns = SourceNamespace()
        assert ns.namespace_name == "source"

    def test_no_docs_returns_empty(self):
        ns = SourceNamespace()
        assert ns.build() == {}

    def test_with_docs(self):
        ns = SourceNamespace()
        docs = [{"text": "doc1"}, {"text": "doc2"}]
        result = ns.build(docs=docs)
        assert result["documents"] == docs
        assert result["count"] == 2

    def test_with_docs_together(self):
        ns = SourceNamespace()
        result = ns.build(docs_together="all content together")
        assert result["content"] == "all content together"
        assert result["docs_together"] == "all content together"
        assert result["summaries"] == "all content together"

    def test_with_both_docs_and_docs_together(self):
        ns = SourceNamespace()
        docs = [{"text": "doc1"}]
        result = ns.build(docs=docs, docs_together="combined")
        assert result["documents"] == docs
        assert result["count"] == 1
        assert result["content"] == "combined"

    def test_empty_docs_list_returns_empty(self):
        ns = SourceNamespace()
        result = ns.build(docs=[])
        assert "documents" not in result


# ── ToolsNamespace ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestToolsNamespace:
    def test_namespace_name(self):
        ns = ToolsNamespace()
        assert ns.namespace_name == "tools"

    def test_none_data_returns_empty(self):
        ns = ToolsNamespace()
        assert ns.build(tools_data=None) == {}

    def test_no_data_returns_empty(self):
        ns = ToolsNamespace()
        assert ns.build() == {}

    def test_safe_types_pass_through(self):
        ns = ToolsNamespace()
        data = {
            "str_tool": "result",
            "dict_tool": {"key": "val"},
            "list_tool": [1, 2],
            "int_tool": 42,
            "float_tool": 3.14,
            "bool_tool": True,
            "none_tool": None,
        }
        result = ns.build(tools_data=data)
        assert result == data

    def test_non_serializable_filtered(self):
        ns = ToolsNamespace()
        data = {"good": "ok", "bad": object()}
        result = ns.build(tools_data=data)
        assert result == {"good": "ok"}


# ── NamespaceBuilder ABC ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestNamespaceBuilderABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            NamespaceBuilder()

    def test_subclass_must_implement_both(self):
        class Incomplete(NamespaceBuilder):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self):
        class Complete(NamespaceBuilder):
            @property
            def namespace_name(self):
                return "test"

            def build(self, **kwargs):
                return {"ok": True}

        inst = Complete()
        assert inst.namespace_name == "test"
        assert inst.build() == {"ok": True}


# ── NamespaceManager ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestNamespaceManager:
    def test_build_context_contains_all_namespaces(self):
        mgr = NamespaceManager()
        ctx = mgr.build_context()
        assert "system" in ctx
        assert "passthrough" in ctx
        assert "source" in ctx
        assert "tools" in ctx

    def test_system_namespace_populated(self):
        mgr = NamespaceManager()
        ctx = mgr.build_context(request_id="r1", user_id="u1")
        assert ctx["system"]["request_id"] == "r1"
        assert ctx["system"]["user_id"] == "u1"

    def test_passthrough_namespace_populated(self):
        mgr = NamespaceManager()
        ctx = mgr.build_context(passthrough_data={"key": "val"})
        assert ctx["passthrough"] == {"key": "val"}

    def test_source_namespace_populated(self):
        mgr = NamespaceManager()
        docs = [{"text": "doc"}]
        ctx = mgr.build_context(docs=docs)
        assert ctx["source"]["count"] == 1

    def test_tools_namespace_populated(self):
        mgr = NamespaceManager()
        ctx = mgr.build_context(tools_data={"search": "results"})
        assert ctx["tools"] == {"search": "results"}

    def test_empty_kwargs_all_namespaces_present(self):
        mgr = NamespaceManager()
        ctx = mgr.build_context()
        for ns in ["system", "passthrough", "source", "tools"]:
            assert ns in ctx
            assert isinstance(ctx[ns], dict)

    def test_builder_exception_returns_empty_namespace(self):
        mgr = NamespaceManager()
        with patch.object(
            mgr._builders["system"], "build", side_effect=RuntimeError("boom")
        ):
            ctx = mgr.build_context()
        assert ctx["system"] == {}
        assert "passthrough" in ctx

    def test_get_builder_existing(self):
        mgr = NamespaceManager()
        builder = mgr.get_builder("system")
        assert isinstance(builder, SystemNamespace)

    def test_get_builder_nonexistent(self):
        mgr = NamespaceManager()
        assert mgr.get_builder("nonexistent") is None
