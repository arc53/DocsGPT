"""Tests for application/agents/tools/api_body_serializer.py"""

import json

import pytest

from application.agents.tools.api_body_serializer import (
    ContentType,
    RequestBodySerializer,
)


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
        # Value is percent-encoded by _serialize_form_value then urlencoded again
        assert "tags=" in body
        assert "a" in body and "b" in body

    def test_dict_value_json_content_type(self):
        body, headers = RequestBodySerializer.serialize(
            {"metadata": {"key": "val"}},
            ContentType.FORM_URLENCODED,
            encoding_rules={"metadata": {"contentType": "application/json"}},
        )
        assert "metadata" in body


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


@pytest.mark.unit
class TestSerializeOctetStream:
    def test_dict_body(self):
        body, headers = RequestBodySerializer.serialize(
            {"key": "val"}, ContentType.OCTET_STREAM
        )
        assert isinstance(body, bytes)
        assert headers["Content-Type"] == "application/octet-stream"


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


@pytest.mark.unit
class TestHelpers:
    def test_percent_encode(self):
        assert RequestBodySerializer._percent_encode("hello world") == "hello%20world"
        assert RequestBodySerializer._percent_encode("a/b") == "a%2Fb"
        assert RequestBodySerializer._percent_encode("safe", safe_chars="/") == "safe"

    def test_escape_xml(self):
        assert "&amp;" in RequestBodySerializer._escape_xml("&")
        assert "&lt;" in RequestBodySerializer._escape_xml("<")
        assert "&gt;" in RequestBodySerializer._escape_xml(">")
        assert "&quot;" in RequestBodySerializer._escape_xml('"')
        assert "&apos;" in RequestBodySerializer._escape_xml("'")

    def test_dict_to_xml_list(self):
        xml = RequestBodySerializer._dict_to_xml({"items": [1, 2, 3]})
        assert "<item>1</item>" in xml
        assert "<item>2</item>" in xml
