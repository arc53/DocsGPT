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


# =====================================================================
# Coverage gap tests for application/parser/schema/base.py  (lines 19, 27, 34)
# =====================================================================


@pytest.mark.unit
class TestDocumentBase:

    def test_document_post_init_raises_on_none_text(self):
        """Cover line 19: Document.__post_init__ raises ValueError for None text."""
        from application.parser.schema.base import Document

        with pytest.raises(ValueError, match="text field not set"):
            Document(text=None)

    def test_document_to_langchain_format(self):
        """Cover line 27: Document.to_langchain_format converts correctly."""
        from application.parser.schema.base import Document

        doc = Document(text="hello world", extra_info={"source": "test"})
        lc_doc = doc.to_langchain_format()
        assert lc_doc.page_content == "hello world"
        assert lc_doc.metadata == {"source": "test"}

    def test_document_to_langchain_format_no_extra_info(self):
        """Cover: to_langchain_format with no extra_info uses empty dict."""
        from application.parser.schema.base import Document

        doc = Document(text="hello")
        lc_doc = doc.to_langchain_format()
        assert lc_doc.metadata == {}

    def test_document_from_langchain_format(self):
        """Cover line 34: Document.from_langchain_format creates Document."""
        from application.parser.schema.base import Document
        from langchain_core.documents import Document as LCDocument

        lc_doc = LCDocument(page_content="test content", metadata={"key": "val"})
        doc = Document.from_langchain_format(lc_doc)
        assert doc.text == "test content"
        assert doc.extra_info == {"key": "val"}

    def test_document_get_type(self):
        """Cover line 24: Document.get_type returns 'Document'."""
        from application.parser.schema.base import Document

        assert Document.get_type() == "Document"
