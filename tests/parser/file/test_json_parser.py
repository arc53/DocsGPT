from pathlib import Path
from unittest.mock import patch, mock_open

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


def test_json_parser_parses_dict_concat():
    parser = JSONParser()
    with patch("builtins.open", mock_open(read_data="{}")):
        with patch("json.load", return_value={"a": 1}):
            result = parser.parse_file(Path("t.json"))
    assert result == "{'a': 1}"


def test_json_parser_parses_list_no_concat():
    parser = JSONParser()
    parser._concat_rows = False
    data = [{"a": 1}, {"b": 2}]
    with patch("builtins.open", mock_open(read_data="[]")):
        with patch("json.load", return_value=data):
            result = parser.parse_file(Path("t.json"))
    assert result == data


def test_json_parser_row_joiner_config():
    parser = JSONParser(row_joiner=" || ")
    with patch("builtins.open", mock_open(read_data="[]")):
        with patch("json.load", return_value=[{"a": 1}, {"b": 2}]):
            result = parser.parse_file(Path("t.json"))
    assert result == "{'a': 1} || {'b': 2}"


def test_json_parser_forwards_json_config():
    def pf(s):
        return 1.23
    parser = JSONParser(json_config={"parse_float": pf})
    with patch("builtins.open", mock_open(read_data="[]")):
        with patch("json.load", return_value=[]) as mock_load:
            parser.parse_file(Path("t.json"))
            assert mock_load.call_args.kwargs.get("parse_float") is pf


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

