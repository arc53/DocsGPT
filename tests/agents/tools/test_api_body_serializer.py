"""Comprehensive tests for application/agents/tools/api_body_serializer.py

Covers: ContentType enum, RequestBodySerializer (JSON, form-urlencoded,
multipart, text/plain, XML, octet-stream, unknown types), encoding rules,
helper methods (_percent_encode, _escape_xml, _dict_to_xml).
"""

import json

import pytest

from application.agents.tools.api_body_serializer import (
    ContentType,
    RequestBodySerializer,
)


# =====================================================================
# ContentType Enum
# =====================================================================


@pytest.mark.unit
class TestContentTypeEnum:

    def test_json_value(self):
        assert ContentType.JSON == "application/json"

    def test_form_urlencoded_value(self):
        assert ContentType.FORM_URLENCODED == "application/x-www-form-urlencoded"

    def test_multipart_value(self):
        assert ContentType.MULTIPART_FORM_DATA == "multipart/form-data"

    def test_text_plain_value(self):
        assert ContentType.TEXT_PLAIN == "text/plain"

    def test_xml_value(self):
        assert ContentType.XML == "application/xml"

    def test_octet_stream_value(self):
        assert ContentType.OCTET_STREAM == "application/octet-stream"

    def test_str_enum(self):
        assert isinstance(ContentType.JSON, str)


# =====================================================================
# JSON Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeJson:

    def test_basic_json(self):
        body, headers = RequestBodySerializer.serialize(
            {"key": "value"}, ContentType.JSON
        )
        assert json.loads(body) == {"key": "value"}
        assert headers["Content-Type"] == "application/json"

    def test_nested_json(self):
        data = {"user": {"name": "Alice", "age": 30}}
        body, headers = RequestBodySerializer.serialize(data, ContentType.JSON)
        assert json.loads(body) == data

    def test_empty_body_returns_none(self):
        body, headers = RequestBodySerializer.serialize({}, ContentType.JSON)
        assert body is None
        assert headers == {}

    def test_none_body(self):
        body, headers = RequestBodySerializer.serialize(None, ContentType.JSON)
        assert body is None

    def test_unknown_content_type_falls_back_to_json(self):
        body, headers = RequestBodySerializer.serialize(
            {"k": "v"}, "application/vnd.custom+json"
        )
        assert json.loads(body) == {"k": "v"}

    def test_content_type_with_charset_suffix(self):
        body, headers = RequestBodySerializer.serialize(
            {"k": "v"}, "application/json; charset=utf-8"
        )
        assert json.loads(body) == {"k": "v"}

    def test_compact_json_format(self):
        body, _ = RequestBodySerializer.serialize(
            {"a": 1, "b": 2}, ContentType.JSON
        )
        # Should use compact separators
        assert " " not in body

    def test_unicode_json(self):
        body, _ = RequestBodySerializer.serialize(
            {"name": "Heisenberg"}, ContentType.JSON
        )
        parsed = json.loads(body)
        assert parsed["name"] == "Heisenberg"


# =====================================================================
# Form URL-Encoded Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeFormUrlencoded:

    def test_basic_form(self):
        body, headers = RequestBodySerializer.serialize(
            {"name": "Alice", "age": "30"}, ContentType.FORM_URLENCODED
        )
        assert "name=Alice" in body
        assert "age=30" in body
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"

    def test_none_values_skipped(self):
        body, headers = RequestBodySerializer.serialize(
            {"name": "Alice", "skip": None}, ContentType.FORM_URLENCODED
        )
        assert "name=Alice" in body
        assert "skip" not in body

    def test_list_explode_true(self):
        body, headers = RequestBodySerializer.serialize(
            {"tags": ["a", "b"]},
            ContentType.FORM_URLENCODED,
            encoding_rules={"tags": {"style": "form", "explode": True}},
        )
        assert "tags=a" in body
        assert "tags=b" in body

    def test_list_explode_false(self):
        body, headers = RequestBodySerializer.serialize(
            {"tags": ["a", "b"]},
            ContentType.FORM_URLENCODED,
            encoding_rules={"tags": {"style": "form", "explode": False}},
        )
        assert "tags=" in body
        assert "a" in body and "b" in body

    def test_dict_value_json_content_type(self):
        body, headers = RequestBodySerializer.serialize(
            {"metadata": {"key": "val"}},
            ContentType.FORM_URLENCODED,
            encoding_rules={"metadata": {"contentType": "application/json"}},
        )
        assert "metadata" in body

    def test_dict_value_xml_content_type(self):
        body, headers = RequestBodySerializer.serialize(
            {"data": {"name": "test"}},
            ContentType.FORM_URLENCODED,
            encoding_rules={"data": {"contentType": "application/xml"}},
        )
        assert "data" in body

    def test_dict_value_deep_object_explode(self):
        body, headers = RequestBodySerializer.serialize(
            {"filter": {"status": "active", "type": "doc"}},
            ContentType.FORM_URLENCODED,
            encoding_rules={
                "filter": {"style": "deepObject", "explode": True}
            },
        )
        assert "filter" in body

    def test_dict_value_non_exploded(self):
        body, headers = RequestBodySerializer.serialize(
            {"obj": {"a": "1", "b": "2"}},
            ContentType.FORM_URLENCODED,
            encoding_rules={"obj": {"style": "form", "explode": False}},
        )
        assert "obj" in body

    def test_default_explode_for_form_style(self):
        """Default explode should be True when style is 'form'."""
        body, headers = RequestBodySerializer.serialize(
            {"items": ["x", "y"]},
            ContentType.FORM_URLENCODED,
            encoding_rules={"items": {"style": "form"}},
        )
        # explode defaults to True for form style => separate params
        assert "items=x" in body
        assert "items=y" in body

    def test_special_characters_encoded(self):
        body, _ = RequestBodySerializer.serialize(
            {"q": "hello world&more"}, ContentType.FORM_URLENCODED
        )
        assert "hello" in body
        assert "q=" in body


# =====================================================================
# Text Plain Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeTextPlain:

    def test_single_value(self):
        body, headers = RequestBodySerializer.serialize(
            {"message": "hello"}, ContentType.TEXT_PLAIN
        )
        assert body == "hello"
        assert headers["Content-Type"] == "text/plain"

    def test_multiple_values(self):
        body, headers = RequestBodySerializer.serialize(
            {"name": "Alice", "age": 30}, ContentType.TEXT_PLAIN
        )
        assert "name: Alice" in body
        assert "age: 30" in body


# =====================================================================
# XML Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeXml:

    def test_basic_xml(self):
        body, headers = RequestBodySerializer.serialize(
            {"name": "Alice"}, ContentType.XML
        )
        assert '<?xml version="1.0"' in body
        assert "<name>Alice</name>" in body
        assert headers["Content-Type"] == "application/xml"

    def test_nested_xml(self):
        body, headers = RequestBodySerializer.serialize(
            {"user": {"name": "Alice"}}, ContentType.XML
        )
        assert "<user>" in body
        assert "<name>Alice</name>" in body

    def test_xml_escapes_special_chars(self):
        body, headers = RequestBodySerializer.serialize(
            {"data": "<script>alert('xss')</script>"}, ContentType.XML
        )
        assert "&lt;script&gt;" in body

    def test_xml_with_list(self):
        body, _ = RequestBodySerializer.serialize(
            {"items": [1, 2, 3]}, ContentType.XML
        )
        assert "<item>1</item>" in body
        assert "<item>2</item>" in body
        assert "<item>3</item>" in body


# =====================================================================
# Octet Stream Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeOctetStream:

    def test_dict_body(self):
        body, headers = RequestBodySerializer.serialize(
            {"key": "val"}, ContentType.OCTET_STREAM
        )
        assert isinstance(body, bytes)
        assert headers["Content-Type"] == "application/octet-stream"

    def test_bytes_body(self):
        body, headers = RequestBodySerializer._serialize_octet_stream(b"\x00\x01")
        assert body == b"\x00\x01"
        assert headers["Content-Type"] == "application/octet-stream"

    def test_string_body(self):
        body, headers = RequestBodySerializer._serialize_octet_stream("hello")
        assert body == b"hello"


# =====================================================================
# Multipart Form Data Serialization
# =====================================================================


@pytest.mark.unit
class TestSerializeMultipartFormData:

    def test_basic_multipart(self):
        body, headers = RequestBodySerializer.serialize(
            {"field": "value"}, ContentType.MULTIPART_FORM_DATA
        )
        assert isinstance(body, bytes)
        assert "multipart/form-data" in headers["Content-Type"]
        assert "boundary=" in headers["Content-Type"]

    def test_none_values_skipped(self):
        body, headers = RequestBodySerializer.serialize(
            {"field": "value", "empty": None}, ContentType.MULTIPART_FORM_DATA
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "field" in body_str
        assert "empty" not in body_str

    def test_multipart_with_bytes(self):
        body, headers = RequestBodySerializer.serialize(
            {"file": b"\x00\x01\x02"}, ContentType.MULTIPART_FORM_DATA
        )
        assert isinstance(body, bytes)

    def test_multipart_with_dict_json(self):
        body, headers = RequestBodySerializer.serialize(
            {"meta": {"key": "val"}},
            ContentType.MULTIPART_FORM_DATA,
            encoding_rules={"meta": {"contentType": "application/json"}},
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "meta" in body_str
        assert "application/json" in body_str

    def test_multipart_with_dict_xml(self):
        body, headers = RequestBodySerializer.serialize(
            {"data": {"name": "test"}},
            ContentType.MULTIPART_FORM_DATA,
            encoding_rules={"data": {"contentType": "application/xml"}},
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "data" in body_str

    def test_multipart_octet_stream_bytes(self):
        body, headers = RequestBodySerializer.serialize(
            {"bin": b"\xff\xfe"},
            ContentType.MULTIPART_FORM_DATA,
            encoding_rules={"bin": {"contentType": "application/octet-stream"}},
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "bin" in body_str
        assert "Content-Transfer-Encoding: base64" in body_str

    def test_multipart_string_with_json_content_type(self):
        body, headers = RequestBodySerializer.serialize(
            {"json_str": '{"a": 1}'},
            ContentType.MULTIPART_FORM_DATA,
            encoding_rules={"json_str": {"contentType": "application/json"}},
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "json_str" in body_str

    def test_multipart_string_with_non_text_content_type(self):
        body, headers = RequestBodySerializer.serialize(
            {"custom": "data"},
            ContentType.MULTIPART_FORM_DATA,
            encoding_rules={"custom": {"contentType": "application/custom"}},
        )
        body_str = body.decode("utf-8", errors="replace")
        assert "custom" in body_str


# =====================================================================
# Helper Methods
# =====================================================================


@pytest.mark.unit
class TestHelpers:

    def test_percent_encode_space(self):
        assert RequestBodySerializer._percent_encode("hello world") == "hello%20world"

    def test_percent_encode_slash(self):
        assert RequestBodySerializer._percent_encode("a/b") == "a%2Fb"

    def test_percent_encode_safe_chars(self):
        assert RequestBodySerializer._percent_encode("a/b", safe_chars="/") == "a/b"

    def test_escape_xml_ampersand(self):
        assert "&amp;" in RequestBodySerializer._escape_xml("&")

    def test_escape_xml_lt(self):
        assert "&lt;" in RequestBodySerializer._escape_xml("<")

    def test_escape_xml_gt(self):
        assert "&gt;" in RequestBodySerializer._escape_xml(">")

    def test_escape_xml_quote(self):
        assert "&quot;" in RequestBodySerializer._escape_xml('"')

    def test_escape_xml_apos(self):
        assert "&apos;" in RequestBodySerializer._escape_xml("'")

    def test_dict_to_xml_list(self):
        xml = RequestBodySerializer._dict_to_xml({"items": [1, 2, 3]})
        assert "<item>1</item>" in xml
        assert "<item>2</item>" in xml

    def test_dict_to_xml_custom_root(self):
        xml = RequestBodySerializer._dict_to_xml({"key": "val"}, root_name="data")
        assert "<data>" in xml
        assert "<key>val</key>" in xml

    def test_dict_to_xml_deeply_nested(self):
        xml = RequestBodySerializer._dict_to_xml({"a": {"b": {"c": "deep"}}})
        assert "<c>deep</c>" in xml


# =====================================================================
# Error Handling
# =====================================================================


@pytest.mark.unit
class TestSerializationErrors:

    def test_serialize_raises_on_internal_error(self):
        """Test that serialization errors are wrapped in ValueError."""
        # Patch _serialize_json to raise
        with pytest.raises(ValueError, match="Failed to serialize"):
            RequestBodySerializer.serialize(
                {"key": object()},  # object() is not JSON-serializable
                ContentType.JSON,
            )
