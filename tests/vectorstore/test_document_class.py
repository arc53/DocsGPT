import pytest
from application.vectorstore.document_class import Document


@pytest.mark.unit
class TestDocument:
    def test_create_document(self):
        doc = Document(page_content="hello world", metadata={"source": "test"})
        assert doc.page_content == "hello world"
        assert doc.metadata == {"source": "test"}

    def test_document_is_string(self):
        doc = Document(page_content="hello world", metadata={})
        assert isinstance(doc, str)
        assert str(doc) == "hello world"

    def test_document_string_equality(self):
        doc = Document(page_content="hello", metadata={"k": "v"})
        assert doc == "hello"

    def test_document_empty_metadata(self):
        doc = Document(page_content="text", metadata={})
        assert doc.metadata == {}

    def test_document_empty_content(self):
        doc = Document(page_content="", metadata={"a": 1})
        assert doc.page_content == ""
        assert doc == ""

    def test_document_preserves_complex_metadata(self):
        meta = {"source": "file.txt", "page": 3, "nested": {"key": "val"}}
        doc = Document(page_content="content", metadata=meta)
        assert doc.metadata["nested"]["key"] == "val"

    def test_document_string_operations(self):
        doc = Document(page_content="hello world", metadata={})
        assert doc.upper() == "HELLO WORLD"
        assert doc.split() == ["hello", "world"]
        assert "world" in doc
