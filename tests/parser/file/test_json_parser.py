import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

from application.parser.file.json_parser import JSONParser


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
    pf = lambda s: 1.23
    parser = JSONParser(json_config={"parse_float": pf})
    with patch("builtins.open", mock_open(read_data="[]")):
        with patch("json.load", return_value=[]) as mock_load:
            parser.parse_file(Path("t.json"))
            assert mock_load.call_args.kwargs.get("parse_float") is pf

