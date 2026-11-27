import json
from decimal import Decimal

import pytest

from docsgpt.parser.file.json_parser import JSONParser


def test_json_init_parser():
    parser = JSONParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_json_parser_parses_dict_concat(tmp_path):
    path = tmp_path / "t.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert JSONParser().parse_file(path) == "{'a': 1}"


def test_json_parser_parses_list_no_concat(tmp_path):
    data = [{"a": 1}, {"b": 2}]
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert JSONParser(concat_rows=False).parse_file(path) == data


def test_json_parser_row_joiner_config(tmp_path):
    path = tmp_path / "t.json"
    path.write_text('[{"a": 1}, {"b": 2}]', encoding="utf-8")
    assert JSONParser(row_joiner=" || ").parse_file(path) == "{'a': 1} || {'b': 2}"


def test_json_parser_forwards_json_config(tmp_path):
    def pf(s):
        return 1.23

    path = tmp_path / "t.json"
    path.write_text("4.56", encoding="utf-8")
    assert JSONParser(json_config={"parse_float": pf}).parse_file(path) == "1.23"


@pytest.mark.parametrize("concat_rows", [True, False])
@pytest.mark.parametrize("value", ["hello", "", "Café\n世界", 42, -1, 1.25, True, False, None])
def test_json_parser_scalar_is_one_row(tmp_path, value, concat_rows):
    path = tmp_path / "scalar.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    result = JSONParser(concat_rows=concat_rows, row_joiner=" || ").parse_file(path)
    assert result == (str(value) if concat_rows else [value])


@pytest.mark.parametrize("concat_rows", [True, False])
@pytest.mark.parametrize("value", [{"a": 1}, [], ["hello", 42, True, None, {"a": 1}]])
def test_json_parser_preserves_container_rows(tmp_path, value, concat_rows):
    path = tmp_path / "container.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    rows = [value] if isinstance(value, dict) else value
    result = JSONParser(concat_rows=concat_rows, row_joiner=" || ").parse_file(path)
    assert result == (" || ".join(str(row) for row in rows) if concat_rows else rows)


@pytest.mark.parametrize("concat_rows", [True, False])
def test_json_parser_scalar_preserves_custom_decoder(tmp_path, concat_rows):
    path = tmp_path / "decimal.json"
    path.write_text("1.25", encoding="utf-8")
    result = JSONParser(concat_rows=concat_rows, json_config={"parse_float": Decimal}).parse_file(path)
    assert result == ("1.25" if concat_rows else [Decimal("1.25")])


def test_json_parser_malformed_json_raises_document_parse_error(tmp_path):
    """A truncated export fails as ``DocumentParseError``, not ``JSONDecodeError``.

    ``SimpleDirectoryReader.load_data`` skips only ``DocumentParseError``, so
    the raw decode error used to abort an entire multi-file ingest, and the
    attachment tasks autoretry everything except that type, re-failing a
    deterministic poison file on every retry.
    """
    from docsgpt.parser.file.base_parser import DocumentParseError

    path = tmp_path / "truncated.json"
    path.write_text('{"key": "value", "list": [1, 2', encoding="utf-8")
    with pytest.raises(DocumentParseError, match="truncated.json"):
        JSONParser().parse_file(path)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b'\xc3\x28{"key": "value"}', id="invalid-prefix"),
        pytest.param(b'"\xed\xa0\x80"', id="raw-surrogate"),
    ],
)
def test_json_parser_invalid_utf8_raises_document_parse_error(tmp_path, content):
    """Bytes that are not valid UTF-8 are not valid JSON and fail the same way."""
    from docsgpt.parser.file.base_parser import DocumentParseError

    path = tmp_path / "binary.json"
    path.write_bytes(content)
    with pytest.raises(DocumentParseError, match="binary.json"):
        JSONParser().parse_file(path)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param('{"x": ' + "9" * 5000 + "}", id="number-over-int-digit-limit"),
        pytest.param("[" * 200_000, id="nesting-past-recursion-limit"),
    ],
)
def test_json_parser_decoder_limits_raise_document_parse_error(tmp_path, content):
    """Input the decoder refuses with ValueError or RecursionError fails the same way."""
    from docsgpt.parser.file.base_parser import DocumentParseError

    path = tmp_path / "poison.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DocumentParseError, match="poison.json"):
        JSONParser().parse_file(path)

