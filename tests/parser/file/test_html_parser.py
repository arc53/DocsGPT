import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
import types

from application.parser.file.html_parser import HTMLParser


@pytest.fixture
def html_parser():
    return HTMLParser()


def test_html_init_parser():
    parser = HTMLParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def test_html_parser_parse_file():
    parser = HTMLParser()
    mock_doc = MagicMock()
    mock_doc.page_content = "Extracted HTML content"
    mock_doc.metadata = {"source": "test.html"}

    import types, sys
    fake_lc = types.ModuleType("langchain_community")
    fake_dl = types.ModuleType("langchain_community.document_loaders")

    bshtml_mock = MagicMock(return_value=MagicMock(load=MagicMock(return_value=[mock_doc])))
    fake_dl.BSHTMLLoader = bshtml_mock
    fake_lc.document_loaders = fake_dl

    with patch.dict(sys.modules, {
        "langchain_community": fake_lc,
        "langchain_community.document_loaders": fake_dl,
    }):
        result = parser.parse_file(Path("test.html"))
        assert result == [mock_doc]
        bshtml_mock.assert_called_once_with(Path("test.html"))
