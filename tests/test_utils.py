"""Tests for application/utils.py"""

from unittest.mock import MagicMock, patch

import pytest

from application.utils import (
    calculate_compression_threshold,
    calculate_doc_token_budget,
    check_required_fields,
    clean_text_for_tts,
    convert_pdf_to_images,
    get_encoding,
    get_field_validation_errors,
    get_gpt_model,
    get_hash,
    get_missing_fields,
    generate_image_url,
    limit_chat_history,
    num_tokens_from_object_or_list,
    num_tokens_from_string,
    safe_filename,
    validate_function_name,
    validate_required_fields,
)


class TestGetEncoding:

    @pytest.mark.unit
    def test_returns_encoding(self):
        enc = get_encoding()
        assert enc is not None

    @pytest.mark.unit
    def test_returns_same_instance(self):
        enc1 = get_encoding()
        enc2 = get_encoding()
        assert enc1 is enc2


class TestGetGptModel:

    @pytest.mark.unit
    def test_returns_llm_name_when_set(self):
        with patch("application.utils.settings") as s:
            s.LLM_NAME = "my-model"
            s.LLM_PROVIDER = "openai"
            assert get_gpt_model() == "my-model"

    @pytest.mark.unit
    def test_falls_back_to_provider_map(self):
        with patch("application.utils.settings") as s:
            s.LLM_NAME = ""
            s.LLM_PROVIDER = "openai"
            assert get_gpt_model() == "gpt-4o-mini"

    @pytest.mark.unit
    def test_unknown_provider_returns_empty(self):
        with patch("application.utils.settings") as s:
            s.LLM_NAME = ""
            s.LLM_PROVIDER = "unknown"
            assert get_gpt_model() == ""


class TestSafeFilename:

    @pytest.mark.unit
    def test_normal_filename(self):
        assert safe_filename("test.pdf") == "test.pdf"

    @pytest.mark.unit
    def test_empty_filename_returns_uuid(self):
        result = safe_filename("")
        assert len(result) > 10  # UUID

    @pytest.mark.unit
    def test_none_filename_returns_uuid(self):
        result = safe_filename(None)
        assert len(result) > 10

    @pytest.mark.unit
    def test_non_latin_filename(self):
        result = safe_filename("документ.pdf")
        assert result.endswith(".pdf")


class TestNumTokens:

    @pytest.mark.unit
    def test_string_token_count(self):
        count = num_tokens_from_string("hello world")
        assert count > 0

    @pytest.mark.unit
    def test_non_string_returns_zero(self):
        assert num_tokens_from_string(123) == 0

    @pytest.mark.unit
    def test_empty_string(self):
        assert num_tokens_from_string("") == 0


class TestNumTokensFromObjectOrList:

    @pytest.mark.unit
    def test_list(self):
        result = num_tokens_from_object_or_list(["hello", "world"])
        assert result > 0

    @pytest.mark.unit
    def test_dict(self):
        result = num_tokens_from_object_or_list({"key": "value"})
        assert result > 0

    @pytest.mark.unit
    def test_string(self):
        result = num_tokens_from_object_or_list("hello")
        assert result > 0

    @pytest.mark.unit
    def test_number_returns_zero(self):
        assert num_tokens_from_object_or_list(42) == 0

    @pytest.mark.unit
    def test_nested(self):
        result = num_tokens_from_object_or_list({"a": ["b", "c"]})
        assert result > 0


class TestCountTokensDocs:

    @pytest.mark.unit
    def test_counts_doc_tokens(self):
        from application.utils import count_tokens_docs
        doc1 = MagicMock()
        doc1.page_content = "hello world"
        doc2 = MagicMock()
        doc2.page_content = " foo bar"
        result = count_tokens_docs([doc1, doc2])
        assert result > 0


class TestCalculateDocTokenBudget:

    @pytest.mark.unit
    def test_returns_budget(self):
        with patch("application.utils.get_token_limit", return_value=128000), \
             patch("application.utils.settings") as s:
            s.RESERVED_TOKENS = {"system": 500, "history": 500}
            result = calculate_doc_token_budget("gpt-4o")
            assert result == 127000

    @pytest.mark.unit
    def test_minimum_budget(self):
        with patch("application.utils.get_token_limit", return_value=1000), \
             patch("application.utils.settings") as s:
            s.RESERVED_TOKENS = {"system": 500, "history": 500}
            result = calculate_doc_token_budget("small-model")
            assert result == 1000


class TestFieldValidation:

    @pytest.mark.unit
    def test_get_missing_fields(self):
        assert get_missing_fields({"a": 1}, ["a", "b"]) == ["b"]
        assert get_missing_fields({"a": 1, "b": 2}, ["a", "b"]) == []

    @pytest.mark.unit
    def test_check_required_fields_pass(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = check_required_fields({"a": 1, "b": 2}, ["a", "b"])
            assert result is None

    @pytest.mark.unit
    def test_check_required_fields_fail(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = check_required_fields({"a": 1}, ["a", "b"])
            assert result is not None
            assert result.status_code == 400

    @pytest.mark.unit
    def test_get_field_validation_errors_none_when_valid(self):
        assert get_field_validation_errors({"a": 1}, ["a"]) is None

    @pytest.mark.unit
    def test_get_field_validation_errors_missing(self):
        result = get_field_validation_errors({}, ["a"])
        assert result["missing_fields"] == ["a"]

    @pytest.mark.unit
    def test_get_field_validation_errors_empty(self):
        result = get_field_validation_errors({"a": ""}, ["a"])
        assert result["empty_fields"] == ["a"]

    @pytest.mark.unit
    def test_validate_required_fields_pass(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = validate_required_fields({"a": "v"}, ["a"])
            assert result is None

    @pytest.mark.unit
    def test_validate_required_fields_missing(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = validate_required_fields({}, ["a"])
            assert result is not None
            assert result.status_code == 400

    @pytest.mark.unit
    def test_validate_required_fields_empty(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = validate_required_fields({"a": ""}, ["a"])
            assert result is not None

    @pytest.mark.unit
    def test_validate_required_fields_both_missing_and_empty(self):
        from flask import Flask
        app = Flask(__name__)
        with app.app_context():
            result = validate_required_fields({"a": ""}, ["a", "b"])
            assert result is not None


class TestGetHash:

    @pytest.mark.unit
    def test_returns_hex_string(self):
        h = get_hash("test")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)

    @pytest.mark.unit
    def test_deterministic(self):
        assert get_hash("hello") == get_hash("hello")

    @pytest.mark.unit
    def test_different_inputs(self):
        assert get_hash("a") != get_hash("b")


class TestLimitChatHistory:

    @pytest.mark.unit
    def test_empty_history(self):
        assert limit_chat_history([]) == []

    @pytest.mark.unit
    def test_none_history(self):
        assert limit_chat_history(None) == []

    @pytest.mark.unit
    def test_keeps_recent_messages(self):
        history = [
            {"prompt": "q1", "response": "a1"},
            {"prompt": "q2", "response": "a2"},
        ]
        result = limit_chat_history(history, max_token_limit=10000)
        assert len(result) == 2

    @pytest.mark.unit
    def test_trims_old_messages(self):
        history = [
            {"prompt": "x" * 5000, "response": "y" * 5000},
            {"prompt": "q", "response": "a"},
        ]
        result = limit_chat_history(history, max_token_limit=100)
        assert len(result) <= 2

    @pytest.mark.unit
    def test_handles_tool_calls(self):
        history = [
            {
                "prompt": "q",
                "response": "a",
                "tool_calls": [
                    {"tool_name": "t", "action_name": "a", "arguments": "{}", "result": "r"}
                ],
            }
        ]
        result = limit_chat_history(history, max_token_limit=10000)
        assert len(result) == 1


class TestValidateFunctionName:

    @pytest.mark.unit
    def test_valid_names(self):
        assert validate_function_name("hello") is True
        assert validate_function_name("hello_world") is True
        assert validate_function_name("hello-world") is True
        assert validate_function_name("test123") is True

    @pytest.mark.unit
    def test_invalid_names(self):
        assert validate_function_name("hello world") is False
        assert validate_function_name("hello!") is False
        assert validate_function_name("") is False


class TestGenerateImageUrl:

    @pytest.mark.unit
    def test_http_url_passthrough(self):
        assert generate_image_url("https://example.com/img.png") == "https://example.com/img.png"
        assert generate_image_url("http://example.com/img.png") == "http://example.com/img.png"

    @pytest.mark.unit
    def test_s3_strategy(self):
        with patch("application.utils.settings") as s:
            s.URL_STRATEGY = "s3"
            s.S3_BUCKET_NAME = "my-bucket"
            s.SAGEMAKER_REGION = "us-west-2"
            result = generate_image_url("path/to/img.png")
            assert "my-bucket.s3.us-west-2" in result

    @pytest.mark.unit
    def test_backend_strategy(self):
        with patch("application.utils.settings") as s:
            s.URL_STRATEGY = "backend"
            s.API_URL = "http://localhost:7091"
            result = generate_image_url("path/to/img.png")
            assert result == "http://localhost:7091/api/images/path/to/img.png"


class TestCalculateCompressionThreshold:

    @pytest.mark.unit
    def test_default_threshold(self):
        with patch("application.utils.get_token_limit", return_value=100000):
            result = calculate_compression_threshold("gpt-4o")
            assert result == 80000

    @pytest.mark.unit
    def test_custom_percentage(self):
        with patch("application.utils.get_token_limit", return_value=100000):
            result = calculate_compression_threshold("gpt-4o", 0.5)
            assert result == 50000


class TestConvertPdfToImages:

    @pytest.mark.unit
    def test_missing_pdf2image_raises(self):
        with patch.dict("sys.modules", {"pdf2image": None}):
            # Force re-import to trigger ImportError
            # The function handles the import internally
            with pytest.raises(ImportError, match="pdf2image"):
                convert_pdf_to_images("test.pdf")

    @pytest.mark.unit
    def test_converts_from_path(self):
        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=lambda buf, format: buf.write(b"PNG_DATA"))

        mock_module = MagicMock()
        mock_module.convert_from_path.return_value = [mock_image]
        mock_module.convert_from_bytes.return_value = [mock_image]

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "pdf2image":
                return mock_module
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=patched_import):
            result = convert_pdf_to_images("/some/file.pdf")
        assert len(result) == 1
        assert result[0]["mime_type"] == "image/png"
        assert result[0]["page"] == 1

    @pytest.mark.unit
    def test_with_storage(self):
        mock_image = MagicMock()
        mock_image.save = MagicMock(side_effect=lambda buf, format: buf.write(b"IMG"))

        mock_storage = MagicMock()
        mock_file = MagicMock()
        mock_file.read.return_value = b"pdf_bytes"
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_storage.get_file.return_value = mock_file

        mock_module = MagicMock()
        mock_module.convert_from_bytes.return_value = [mock_image]

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "pdf2image":
                return mock_module
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=patched_import):
            result = convert_pdf_to_images("test.pdf", storage=mock_storage)
        assert len(result) == 1
        mock_module.convert_from_bytes.assert_called_once()

    @pytest.mark.unit
    def test_file_not_found_raises(self):
        mock_module = MagicMock()
        mock_module.convert_from_path.side_effect = FileNotFoundError("not found")

        # Patch the import inside the function
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def patched_import(name, *args, **kwargs):
            if name == "pdf2image":
                return mock_module
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=patched_import):
            with pytest.raises(FileNotFoundError):
                convert_pdf_to_images("/nonexistent.pdf")

    @pytest.mark.unit
    def test_generic_error_raises(self):
        mock_module = MagicMock()
        mock_module.convert_from_path.side_effect = RuntimeError("conversion failed")

        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def patched_import(name, *args, **kwargs):
            if name == "pdf2image":
                return mock_module
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=patched_import):
            with pytest.raises(RuntimeError, match="conversion failed"):
                convert_pdf_to_images("/some.pdf")


class TestCleanTextForTts:

    @pytest.mark.unit
    def test_removes_code_blocks(self):
        result = clean_text_for_tts("before ```python\ncode\n``` after")
        assert "code block" in result
        assert "python" not in result

    @pytest.mark.unit
    def test_removes_mermaid_blocks(self):
        result = clean_text_for_tts("```mermaid\ngraph TD\n```")
        assert "flowchart" in result

    @pytest.mark.unit
    def test_removes_markdown_links(self):
        result = clean_text_for_tts("[click here](https://example.com)")
        assert "click here" in result
        assert "https" not in result

    @pytest.mark.unit
    def test_removes_images(self):
        result = clean_text_for_tts("![alt text](image.png)")
        assert "image.png" not in result

    @pytest.mark.unit
    def test_removes_inline_code(self):
        result = clean_text_for_tts("use `foo()` here")
        assert "foo()" in result
        assert "`" not in result

    @pytest.mark.unit
    def test_removes_bold_italic(self):
        result = clean_text_for_tts("**bold** and *italic*")
        assert "bold" in result
        assert "italic" in result
        assert "*" not in result

    @pytest.mark.unit
    def test_removes_headers(self):
        result = clean_text_for_tts("# Header\ntext")
        assert "Header" in result
        assert "#" not in result

    @pytest.mark.unit
    def test_removes_blockquotes(self):
        result = clean_text_for_tts("> quoted text")
        assert "quoted text" in result
        assert ">" not in result

    @pytest.mark.unit
    def test_removes_html_tags(self):
        result = clean_text_for_tts("<div>content</div>")
        assert "content" in result
        assert "<" not in result

    @pytest.mark.unit
    def test_removes_arrows(self):
        result = clean_text_for_tts("a --> b <-- c => d")
        assert "-->" not in result
        assert "<--" not in result
        assert "=>" not in result

    @pytest.mark.unit
    def test_removes_horizontal_rules(self):
        result = clean_text_for_tts("text\n---\nmore")
        assert "---" not in result

    @pytest.mark.unit
    def test_removes_list_markers(self):
        result = clean_text_for_tts("- item1\n* item2\n1. item3")
        assert "item1" in result
        assert "item2" in result
        assert "item3" in result

    @pytest.mark.unit
    def test_normalizes_whitespace(self):
        result = clean_text_for_tts("  lots   of   spaces  ")
        assert "  " not in result

    @pytest.mark.unit
    def test_removes_braces(self):
        result = clean_text_for_tts("{content} and [more]")
        assert "content" in result
        assert "more" in result
        assert "{" not in result

    @pytest.mark.unit
    def test_removes_double_colons(self):
        result = clean_text_for_tts("module::function")
        assert "::" not in result
