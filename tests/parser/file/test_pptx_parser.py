import pytest
from pathlib import Path
from unittest.mock import patch

from application.parser.file.pptx_parser import PPTXParser


def test_pptx_init_parser():
    parser = PPTXParser()
    assert isinstance(parser._init_parser(), dict)
    assert not parser.parser_config_set
    parser.init_parser()
    assert parser.parser_config_set


def _fake_presentation_with(slides_shapes_texts):
    class Shape:
        def __init__(self, text=None):
            if text is not None:
                self.text = text
    class Slide:
        def __init__(self, texts):
            self.shapes = [Shape(t) for t in texts]
    class Pres:
        def __init__(self, _file):
            self.slides = [Slide(texts) for texts in slides_shapes_texts]
    return Pres


def test_pptx_parser_concat_true():
    slides = [["Hello ", "World"], ["Slide2"]]
    FakePres = _fake_presentation_with(slides)
    import sys, types
    fake_pptx = types.ModuleType("pptx")
    fake_pptx.Presentation = FakePres
    parser = PPTXParser()
    with patch.dict(sys.modules, {"pptx": fake_pptx}):
        result = parser.parse_file(Path("deck.pptx"))
    assert result == "Hello World\nSlide2"


def test_pptx_parser_list_mode():
    slides = [[" A ", "B"], [" C "]]
    FakePres = _fake_presentation_with(slides)
    import sys, types
    fake_pptx = types.ModuleType("pptx")
    fake_pptx.Presentation = FakePres
    parser = PPTXParser()
    parser._concat_slides = False
    with patch.dict(sys.modules, {"pptx": fake_pptx}):
        result = parser.parse_file(Path("deck.pptx"))
    assert result == ["A B", "C"]


def test_pptx_parser_import_error():
    parser = PPTXParser()
    import sys
    with patch.dict(sys.modules, {"pptx": None}):
        with pytest.raises(ImportError, match="pptx module is required to read .PPTX files"):
            parser.parse_file(Path("missing.pptx"))

