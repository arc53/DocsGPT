import json
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from docsgpt.parser.file.base_parser import DocumentParseError
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
    assert result == ["{'a': 1}", "{'b': 2}"]


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
@pytest.mark.parametrize(
    "value, expected_rows",
    [
        ("DocsGPT keeps words together", ["DocsGPT keeps words together"]),
        ("", [""]),
        (42, ["42"]),
        (3.5, ["3.5"]),
        (True, ["True"]),
        (False, ["False"]),
        (None, ["None"]),
        ({"name": "DocsGPT"}, ["{'name': 'DocsGPT'}"]),
        (
            [{"name": "DocsGPT"}, 42, False, None, ["nested"]],
            ["{'name': 'DocsGPT'}", "42", "False", "None", "['nested']"],
        ),
        (["first", "second"], ["first", "second"]),
        ([], []),
    ],
)
def test_json_parser_returns_text_for_real_files(
    tmp_path: Path, concat_rows: bool, value: object, expected_rows: list[str]
) -> None:
    """Every JSON value produces text suitable for downstream document ingestion."""
    path = tmp_path / "source.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    result = JSONParser(concat_rows=concat_rows, row_joiner="\n\n").parse_file(path)

    expected = "\n\n".join(expected_rows) if concat_rows else expected_rows
    assert result == expected
    if not concat_rows:
        assert all(isinstance(row, str) for row in result)


def test_json_parser_preserves_decoding_hook_output(tmp_path: Path) -> None:
    """Custom JSON decoders still determine the text of a row."""
    path = tmp_path / "source.json"
    path.write_text("[1.25]", encoding="utf-8")

    result = JSONParser(
        concat_rows=False, json_config={"parse_float": lambda value: f"decimal:{value}"}
    ).parse_file(path)

    assert result == ["decimal:1.25"]


@pytest.mark.parametrize("contents", [b'{"unfinished":', b'"invalid \xff"'])
def test_json_parser_reports_invalid_files_as_parse_errors(tmp_path: Path, contents: bytes) -> None:
    """Bad JSON must use the error type that lets batch ingestion skip a file."""
    path = tmp_path / "broken.json"
    path.write_bytes(contents)

    with pytest.raises(DocumentParseError, match="broken.json") as exc_info:
        JSONParser().parse_file(path)

    assert isinstance(exc_info.value.__cause__, (json.JSONDecodeError, UnicodeDecodeError))


def test_json_parser_keeps_valid_files_in_a_mixed_upload(tmp_path: Path) -> None:
    """One malformed JSON file must not abort the remaining source documents."""
    from docsgpt.parser.file.bulk import SimpleDirectoryReader

    broken = tmp_path / "broken.json"
    broken.write_text('{"unfinished":', encoding="utf-8")
    valid = tmp_path / "valid.json"
    valid.write_text('"The support email is help@example.com"', encoding="utf-8")
    reader = SimpleDirectoryReader(
        input_files=[str(broken), str(valid)], file_extractor={".json": JSONParser()}
    )

    documents = reader.load_data()

    assert [document.text for document in documents] == ["The support email is help@example.com"]
    assert len(reader.failed_files) == 1
    assert reader.failed_files[0][0] == broken


def test_json_parser_rejects_an_upload_with_no_valid_files(tmp_path: Path) -> None:
    """A lone malformed JSON document is a failed upload, not indexed error text."""
    from docsgpt.parser.file.bulk import SimpleDirectoryReader

    path = tmp_path / "broken.json"
    path.write_text('{"unfinished":', encoding="utf-8")
    reader = SimpleDirectoryReader(
        input_files=[str(path)], file_extractor={".json": JSONParser()}
    )

    with pytest.raises(DocumentParseError, match="broken.json"):
        reader.load_data()
