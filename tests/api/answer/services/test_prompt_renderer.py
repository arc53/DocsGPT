import pytest


@pytest.mark.unit
class TestTemplateEngine:

    def test_render_simple_template(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        result = engine.render("Hello {{ name }}", {"name": "World"})

        assert result == "Hello World"

    def test_render_with_namespace(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        context = {
            "user": {"name": "Alice", "role": "admin"},
            "system": {"date": "2025-10-22"},
        }
        result = engine.render(
            "{{ user.name }} is a {{ user.role }} on {{ system.date }}", context
        )

        assert result == "Alice is a admin on 2025-10-22"

    def test_render_empty_template(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        result = engine.render("", {"key": "value"})

        assert result == ""

    def test_render_template_without_variables(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        result = engine.render("Just plain text", {})

        assert result == "Just plain text"

    def test_render_undefined_variable_returns_empty_string(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()

        result = engine.render("Hello {{ undefined_var }}", {})
        assert result == "Hello "

    def test_render_syntax_error_raises_error(self):
        from application.templates.template_engine import (
            TemplateEngine,
            TemplateRenderError,
        )

        engine = TemplateEngine()

        with pytest.raises(TemplateRenderError, match="Template syntax error"):
            engine.render("Hello {{ name", {"name": "World"})

    def test_validate_template_valid(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        assert engine.validate_template("Valid {{ variable }}") is True

    def test_validate_template_invalid(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        assert engine.validate_template("Invalid {{ variable") is False

    def test_validate_empty_template(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        assert engine.validate_template("") is True

    def test_extract_variables(self):
        from application.templates.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = "{{ user.name }} and {{ user.email }}"

        result = engine.extract_variables(template)

        assert isinstance(result, set)


@pytest.mark.unit
class TestSystemNamespace:

    def test_system_namespace_build(self):
        from application.templates.namespaces import SystemNamespace

        builder = SystemNamespace()
        context = builder.build(
            request_id="req_123", user_id="user_456", extra_param="ignored"
        )

        assert context["request_id"] == "req_123"
        assert context["user_id"] == "user_456"
        assert "date" in context
        assert "time" in context
        assert "timestamp" in context

    def test_system_namespace_generates_request_id(self):
        from application.templates.namespaces import SystemNamespace

        builder = SystemNamespace()
        context = builder.build(user_id="user_123")

        assert context["request_id"] is not None
        assert len(context["request_id"]) > 0

    def test_system_namespace_name(self):
        from application.templates.namespaces import SystemNamespace

        builder = SystemNamespace()
        assert builder.namespace_name == "system"

    def test_system_namespace_date_format(self):
        from application.templates.namespaces import SystemNamespace

        builder = SystemNamespace()
        context = builder.build()

        import re

        assert re.match(r"\d{4}-\d{2}-\d{2}", context["date"])
        assert re.match(r"\d{2}:\d{2}:\d{2}", context["time"])


@pytest.mark.unit
class TestPassthroughNamespace:

    def test_passthrough_namespace_build(self):
        from application.templates.namespaces import PassthroughNamespace

        builder = PassthroughNamespace()
        passthrough_data = {"company": "Acme", "user_name": "John", "count": 42}

        context = builder.build(passthrough_data=passthrough_data)

        assert context["company"] == "Acme"
        assert context["user_name"] == "John"
        assert context["count"] == 42

    def test_passthrough_namespace_empty(self):
        from application.templates.namespaces import PassthroughNamespace

        builder = PassthroughNamespace()
        context = builder.build(passthrough_data=None)

        assert context == {}

    def test_passthrough_namespace_filters_unsafe_values(self):
        from application.templates.namespaces import PassthroughNamespace

        builder = PassthroughNamespace()
        passthrough_data = {
            "safe_string": "value",
            "unsafe_object": {"key": "value"},
            "safe_bool": True,
            "unsafe_list": [1, 2, 3],
            "safe_float": 3.14,
        }

        context = builder.build(passthrough_data=passthrough_data)

        assert context["safe_string"] == "value"
        assert context["safe_bool"] is True
        assert context["safe_float"] == 3.14
        assert "unsafe_object" not in context
        assert "unsafe_list" not in context

    def test_passthrough_namespace_allows_none_values(self):
        from application.templates.namespaces import PassthroughNamespace

        builder = PassthroughNamespace()
        passthrough_data = {"nullable_field": None}

        context = builder.build(passthrough_data=passthrough_data)

        assert context["nullable_field"] is None

    def test_passthrough_namespace_name(self):
        from application.templates.namespaces import PassthroughNamespace

        builder = PassthroughNamespace()
        assert builder.namespace_name == "passthrough"


@pytest.mark.unit
class TestSourceNamespace:

    def test_source_namespace_build_with_docs(self):
        from application.templates.namespaces import SourceNamespace

        builder = SourceNamespace()
        docs = [
            {"text": "Doc 1", "filename": "file1.txt"},
            {"text": "Doc 2", "filename": "file2.txt"},
        ]
        docs_together = "Doc 1 content\n\nDoc 2 content"

        context = builder.build(docs=docs, docs_together=docs_together)

        assert context["documents"] == docs
        assert context["count"] == 2
        assert context["content"] == docs_together
        assert context["summaries"] == docs_together

    def test_source_namespace_build_empty(self):
        from application.templates.namespaces import SourceNamespace

        builder = SourceNamespace()
        context = builder.build(docs=None, docs_together=None)

        assert context == {}

    def test_source_namespace_build_docs_only(self):
        from application.templates.namespaces import SourceNamespace

        builder = SourceNamespace()
        docs = [{"text": "Doc 1"}]

        context = builder.build(docs=docs)

        assert context["documents"] == docs
        assert context["count"] == 1
        assert "content" not in context

    def test_source_namespace_build_docs_together_only(self):
        from application.templates.namespaces import SourceNamespace

        builder = SourceNamespace()
        docs_together = "Content here"

        context = builder.build(docs_together=docs_together)

        assert context["content"] == docs_together
        assert context["summaries"] == docs_together
        assert "documents" not in context

    def test_source_namespace_name(self):
        from application.templates.namespaces import SourceNamespace

        builder = SourceNamespace()
        assert builder.namespace_name == "source"


@pytest.mark.unit
class TestToolsNamespace:

    def test_tools_namespace_build_with_memory_data(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()
        tools_data = {
            "memory": {"root": "Files:\n- /notes.txt\n- /tasks.txt", "available": True}
        }

        context = builder.build(tools_data=tools_data)

        assert context["memory"]["root"] == "Files:\n- /notes.txt\n- /tasks.txt"
        assert context["memory"]["available"] is True

    def test_tools_namespace_build_empty(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()
        context = builder.build(tools_data=None)

        assert context == {}

    def test_tools_namespace_build_multiple_tools(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()
        tools_data = {
            "memory": {"root": "content", "available": True},
            "search": {"results": ["result1", "result2"]},
            "api": {"status": "success"},
        }

        context = builder.build(tools_data=tools_data)

        assert "memory" in context
        assert "search" in context
        assert "api" in context
        assert context["memory"]["root"] == "content"
        assert context["search"]["results"] == ["result1", "result2"]
        assert context["api"]["status"] == "success"

    def test_tools_namespace_filters_unsafe_values(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()

        class UnsafeObject:
            pass

        tools_data = {"safe_tool": {"result": "success"}, "unsafe_tool": UnsafeObject()}

        context = builder.build(tools_data=tools_data)

        assert "safe_tool" in context
        assert "unsafe_tool" not in context

    def test_tools_namespace_name(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()
        assert builder.namespace_name == "tools"

    def test_tools_namespace_with_empty_dict(self):
        from application.templates.namespaces import ToolsNamespace

        builder = ToolsNamespace()
        context = builder.build(tools_data={})

        assert context == {}


@pytest.mark.unit
class TestNamespaceManagerWithTools:

    def test_namespace_manager_includes_tools_in_context(self):
        from application.templates.namespaces import NamespaceManager

        manager = NamespaceManager()
        tools_data = {"memory": {"root": "content", "available": True}}

        context = manager.build_context(tools_data=tools_data)

        assert "tools" in context
        assert context["tools"]["memory"]["root"] == "content"

    def test_namespace_manager_build_context_all_namespaces(self):
        from application.templates.namespaces import NamespaceManager

        manager = NamespaceManager()
        context = manager.build_context(
            request_id="req_123",
            user_id="user_456",
            passthrough_data={"key": "value"},
            docs_together="Document content",
            tools_data={"memory": {"root": "notes"}},
        )

        assert "system" in context
        assert "passthrough" in context
        assert "source" in context
        assert "tools" in context
        assert context["tools"]["memory"]["root"] == "notes"

    def test_namespace_manager_build_context_partial_data(self):
        from application.templates.namespaces import NamespaceManager

        manager = NamespaceManager()
        context = manager.build_context(request_id="req_123")

        assert "system" in context
        assert context["system"]["request_id"] == "req_123"

    def test_namespace_manager_get_builder(self):
        from application.templates.namespaces import NamespaceManager, SystemNamespace

        manager = NamespaceManager()
        builder = manager.get_builder("system")

        assert isinstance(builder, SystemNamespace)

    def test_namespace_manager_get_builder_nonexistent(self):
        from application.templates.namespaces import NamespaceManager

        manager = NamespaceManager()
        builder = manager.get_builder("nonexistent")

        assert builder is None

    def test_namespace_manager_handles_builder_exceptions(self):
        from unittest.mock import patch

        from application.templates.namespaces import NamespaceManager

        manager = NamespaceManager()

        with patch.object(
            manager._builders["system"],
            "build",
            side_effect=Exception("Builder error"),
        ):
            context = manager.build_context()
            # Namespace should be present but empty when builder fails

            assert "system" in context
            assert context["system"] == {}


@pytest.mark.unit
class TestPromptRenderer:

    def test_render_prompt_with_template_syntax(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Hello {{ system.user_id }}, today is {{ system.date }}"

        result = renderer.render_prompt(prompt, user_id="user_123")

        assert "user_123" in result
        assert "202" in result

    def test_render_prompt_with_passthrough_data(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Company: {{ passthrough.company }}\nUser: {{ passthrough.user_name }}"
        passthrough_data = {"company": "Acme", "user_name": "John"}

        result = renderer.render_prompt(prompt, passthrough_data=passthrough_data)

        assert "Company: Acme" in result
        assert "User: John" in result

    def test_render_prompt_with_source_docs(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Use this information:\n{{ source.content }}"
        docs_together = "Important document content"

        result = renderer.render_prompt(prompt, docs_together=docs_together)

        assert "Use this information:" in result
        assert "Important document content" in result

    def test_render_prompt_empty_content(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        result = renderer.render_prompt("")

        assert result == ""

    def test_render_prompt_legacy_format_with_summaries(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Context: {summaries}\nQuestion: What is this?"
        docs_together = "This is the document content"

        result = renderer.render_prompt(prompt, docs_together=docs_together)

        assert "Context: This is the document content" in result

    def test_render_prompt_legacy_format_without_docs(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Context: {summaries}\nQuestion: What is this?"

        result = renderer.render_prompt(prompt)

        assert "Context: {summaries}" in result

    def test_render_prompt_combined_namespace_variables(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "User: {{ passthrough.user }}, Date: {{ system.date }}, Docs: {{ source.content }}"
        passthrough_data = {"user": "Alice"}
        docs_together = "Doc content"

        result = renderer.render_prompt(
            prompt,
            passthrough_data=passthrough_data,
            docs_together=docs_together,
        )

        assert "User: Alice" in result
        assert "Date: 202" in result
        assert "Doc content" in result

    def test_render_prompt_with_tools_data(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Memory contents:\n{{ tools.memory.root }}\n\nStatus: {{ tools.memory.available }}"
        tools_data = {
            "memory": {"root": "Files:\n- /notes.txt\n- /tasks.txt", "available": True}
        }

        result = renderer.render_prompt(prompt, tools_data=tools_data)

        assert "Memory contents:" in result
        assert "Files:" in result
        assert "/notes.txt" in result
        assert "/tasks.txt" in result
        assert "Status: True" in result

    def test_render_prompt_with_all_namespaces(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = """
System: {{ system.date }}
User: {{ passthrough.user }}
Docs: {{ source.content }}
Memory: {{ tools.memory.root }}
"""
        passthrough_data = {"user": "Alice"}
        docs_together = "Important docs"
        tools_data = {"memory": {"root": "Notes content", "available": True}}

        result = renderer.render_prompt(
            prompt,
            passthrough_data=passthrough_data,
            docs_together=docs_together,
            tools_data=tools_data,
        )

        assert "202" in result
        assert "Alice" in result
        assert "Important docs" in result
        assert "Notes content" in result

    def test_render_prompt_undefined_variable_returns_empty_string(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Hello {{ undefined_var }}"

        result = renderer.render_prompt(prompt)
        assert result == "Hello "

    def test_render_prompt_with_undefined_variable_in_template(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Hello {{ undefined_name }}"

        result = renderer.render_prompt(prompt)
        assert result == "Hello "

    def test_validate_template_valid(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        assert renderer.validate_template("Valid {{ variable }}") is True

    def test_validate_template_invalid(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        assert renderer.validate_template("Invalid {{ variable") is False

    def test_extract_variables(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        template = "{{ var1 }} and {{ var2 }}"

        result = renderer.extract_variables(template)

        assert isinstance(result, set)

    def test_uses_template_syntax_detection(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()

        assert renderer._uses_template_syntax("Text with {{ var }}") is True
        assert renderer._uses_template_syntax("Text with {var}") is False
        assert renderer._uses_template_syntax("Plain text") is False

    def test_apply_legacy_substitutions(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Use {summaries} to answer"
        docs_together = "Important info"

        result = renderer._apply_legacy_substitutions(prompt, docs_together)

        assert "Use Important info to answer" in result

    def test_apply_legacy_substitutions_without_docs(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "Use {summaries} to answer"

        result = renderer._apply_legacy_substitutions(prompt, None)

        assert result == prompt


@pytest.mark.unit
class TestPromptRendererIntegration:

    def test_render_prompt_real_world_scenario(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = "You are helping {{ passthrough.company }}.\n\nUser: {{ passthrough.user_name }}\n\nRequest ID: {{ system.request_id }}\n\nDate: {{ system.date }}\n\nReference Documents:\n\n{{ source.content }}\n\nPlease answer the question professionally."

        passthrough_data = {"company": "Tech Corp", "user_name": "Alice"}
        docs_together = "Document 1: Technical specs\nDocument 2: Requirements"

        result = renderer.render_prompt(
            prompt,
            request_id="req_123",
            user_id="user_456",
            passthrough_data=passthrough_data,
            docs_together=docs_together,
        )

        assert "Tech Corp" in result
        assert "Alice" in result
        assert "req_123" in result
        assert "Technical specs" in result
        assert "professionally" in result

    def test_render_prompt_multiple_doc_references(self):
        from application.api.answer.services.prompt_renderer import PromptRenderer

        renderer = PromptRenderer()
        prompt = """Documents: {{ source.content }} \n\nAlso summaries: {{ source.summaries }}"""
        docs_together = "Content here"

        result = renderer.render_prompt(prompt, docs_together=docs_together)

        assert result.count("Content here") == 2


@pytest.mark.unit
class TestStreamProcessorPromptRendering:

    def test_stream_processor_pre_fetch_docs_none_doc_mode(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test question", "isNoneDoc": True}
        processor = StreamProcessor(request_data, None)

        docs_together, docs_list = processor.pre_fetch_docs("Test question")

        assert docs_together is None
        assert docs_list is None

    def test_pre_fetch_tools_disabled_globally(self, mock_mongo_db, monkeypatch):
        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ENABLE_TOOL_PREFETCH", False)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        result = processor.pre_fetch_tools()

        assert result is None

    def test_pre_fetch_tools_disabled_per_request(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "test", "disable_tool_prefetch": True}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        result = processor.pre_fetch_tools()

        assert result is None

    def test_pre_fetch_tools_skips_tool_with_no_actions(self, mock_mongo_db):
        from unittest.mock import MagicMock, patch

        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.mongo_db import MongoDB
        from bson import ObjectId

        db = MongoDB.get_client()[list(MongoDB.get_client().keys())[0]]
        tool_doc = {
            "_id": ObjectId(),
            "name": "memory",
            "user": "user1",
            "status": True,
            "config": {},
        }
        db["user_tools"].insert_one(tool_doc)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            # Tool has no actions
            mock_tool.get_actions_metadata.return_value = []

            result = processor.pre_fetch_tools()

            # Should return None when tool has no actions
            assert result is None

    def test_pre_fetch_tools_enabled_by_default(self, mock_mongo_db, monkeypatch):
        from unittest.mock import MagicMock, patch

        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.mongo_db import MongoDB
        from bson import ObjectId

        db = MongoDB.get_client()[list(MongoDB.get_client().keys())[0]]
        tool_doc = {
            "_id": ObjectId(),
            "name": "memory",
            "user": "user1",
            "status": True,
            "config": {},
        }
        db["user_tools"].insert_one(tool_doc)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance returned by load_tool
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            # Mock get_actions_metadata on the tool instance
            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "description": "List files", "parameters": {"properties": {}}}
            ]
            mock_tool.execute_action.return_value = "Directory: /\n- file.txt"

            result = processor.pre_fetch_tools()

            assert result is not None
            assert "memory" in result
            assert "memory_ls" in result["memory"]

    def test_pre_fetch_tools_no_tools_configured(self, mock_mongo_db):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        result = processor.pre_fetch_tools()

        assert result is None

    def test_pre_fetch_tools_memory_returns_error(self, mock_mongo_db):
        from unittest.mock import MagicMock, patch

        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.mongo_db import MongoDB
        from bson import ObjectId

        db = MongoDB.get_client()[list(MongoDB.get_client().keys())[0]]
        tool_doc = {
            "_id": ObjectId(),
            "name": "memory",
            "user": "user1",
            "status": True,
            "config": {},
        }
        db["user_tools"].insert_one(tool_doc)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "description": "List files", "parameters": {"properties": {}}}
            ]
            # Simulate execution error
            mock_tool.execute_action.side_effect = Exception("Tool error")

            result = processor.pre_fetch_tools()

            # Should return None when all actions fail
            assert result is None

    def test_pre_fetch_tools_memory_returns_empty(self, mock_mongo_db):
        from unittest.mock import MagicMock, patch

        from application.api.answer.services.stream_processor import StreamProcessor
        from application.core.mongo_db import MongoDB
        from bson import ObjectId

        db = MongoDB.get_client()[list(MongoDB.get_client().keys())[0]]
        tool_doc = {
            "_id": ObjectId(),
            "name": "memory",
            "user": "user1",
            "status": True,
            "config": {},
        }
        db["user_tools"].insert_one(tool_doc)

        request_data = {"question": "test"}
        processor = StreamProcessor(request_data, {"sub": "user1"})

        with patch(
            "application.agents.tools.tool_manager.ToolManager"
        ) as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            # Mock the tool instance
            mock_tool = MagicMock()
            mock_manager.load_tool.return_value = mock_tool

            mock_tool.get_actions_metadata.return_value = [
                {"name": "memory_ls", "description": "List files", "parameters": {"properties": {}}}
            ]
            # Return empty string
            mock_tool.execute_action.return_value = ""

            result = processor.pre_fetch_tools()

            # Empty result should still be included
            assert result is not None
            assert "memory" in result
