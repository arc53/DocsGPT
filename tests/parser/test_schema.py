import pytest

from application.parser.schema.schema import BaseDocument


class ConcreteDoc(BaseDocument):
    @classmethod
    def get_type(cls) -> str:
        return "test"


@pytest.mark.unit
class TestBaseDocument:

    def test_get_text(self):
        doc = ConcreteDoc(text="hello")
        assert doc.get_text() == "hello"

    def test_get_text_raises_when_none(self):
        doc = ConcreteDoc()
        with pytest.raises(ValueError, match="text field not set"):
            doc.get_text()

    def test_get_doc_id(self):
        doc = ConcreteDoc(text="x", doc_id="doc1")
        assert doc.get_doc_id() == "doc1"

    def test_get_doc_id_raises_when_none(self):
        doc = ConcreteDoc(text="x")
        with pytest.raises(ValueError, match="doc_id not set"):
            doc.get_doc_id()

    def test_is_doc_id_none(self):
        doc = ConcreteDoc(text="x")
        assert doc.is_doc_id_none is True

    def test_is_doc_id_not_none(self):
        doc = ConcreteDoc(text="x", doc_id="y")
        assert doc.is_doc_id_none is False

    def test_get_embedding(self):
        doc = ConcreteDoc(text="x", embedding=[1.0, 2.0])
        assert doc.get_embedding() == [1.0, 2.0]

    def test_get_embedding_raises_when_none(self):
        doc = ConcreteDoc(text="x")
        with pytest.raises(ValueError, match="embedding not set"):
            doc.get_embedding()

    def test_extra_info_str(self):
        doc = ConcreteDoc(text="x", extra_info={"key": "value", "num": 42})
        result = doc.extra_info_str
        assert "key: value" in result
        assert "num: 42" in result

    def test_extra_info_str_none(self):
        doc = ConcreteDoc(text="x")
        assert doc.extra_info_str is None
