import pytest
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse

from application.parser.remote.web_loader import WebLoader, headers
from application.parser.schema.base import Document
from langchain.docstore.document import Document as LCDocument


@pytest.fixture
def web_loader():
    return WebLoader()


@pytest.fixture
def mock_langchain_document():
    """Create a mock LangChain document."""
    doc = MagicMock(spec=LCDocument)
    doc.page_content = "Test web page content"
    doc.metadata = {"source": "https://example.com", "title": "Test Page"}
    return doc


@pytest.fixture
def mock_web_base_loader():
    """Create a mock WebBaseLoader class."""
    mock_loader_class = MagicMock()
    mock_loader_instance = MagicMock()
    mock_loader_class.return_value = mock_loader_instance
    return mock_loader_class, mock_loader_instance


class TestWebLoaderInitialization:
    """Test WebLoader initialization."""

    def test_init(self, web_loader):
        """Test WebLoader initialization."""
        assert web_loader.loader is not None
        from langchain_community.document_loaders import WebBaseLoader
        assert web_loader.loader == WebBaseLoader


class TestWebLoaderHeaders:
    """Test WebLoader headers configuration."""

    def test_headers_defined(self):
        """Test that headers are properly defined."""
        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Referer" in headers
        assert "DNT" in headers
        assert "Connection" in headers
        assert "Upgrade-Insecure-Requests" in headers

    def test_headers_values(self):
        """Test header values are reasonable."""
        assert headers["User-Agent"] == "Mozilla/5.0"
        assert "text/html" in headers["Accept"]
        assert headers["Referer"] == "https://www.google.com/"
        assert headers["DNT"] == "1"
        assert headers["Connection"] == "keep-alive"


class TestWebLoaderLoadData:
    """Test WebLoader load_data method."""

    def test_load_data_single_url_string(self, web_loader, mock_langchain_document):
        """Test loading data from a single URL passed as string."""

        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [mock_langchain_document]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1
        assert isinstance(result[0], Document)
        assert result[0].text == "Test web page content"
        assert result[0].extra_info == {"source": "https://example.com", "title": "Test Page"}

        mock_web_base_loader_class.assert_called_once_with(["https://example.com"], header_template=headers)
        mock_loader_instance.load.assert_called_once()

    def test_load_data_multiple_urls_list(self, web_loader):
        """Test loading data from multiple URLs passed as list."""
        
        doc1 = MagicMock(spec=LCDocument)
        doc1.page_content = "Content from site 1"
        doc1.metadata = {"source": "https://site1.com"}

        doc2 = MagicMock(spec=LCDocument)
        doc2.page_content = "Content from site 2"
        doc2.metadata = {"source": "https://site2.com"}

       
        mock_loader_instance1 = MagicMock()
        mock_loader_instance1.load.return_value = [doc1]

        mock_loader_instance2 = MagicMock()
        mock_loader_instance2.load.return_value = [doc2]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.side_effect = [mock_loader_instance1, mock_loader_instance2]

        web_loader.loader = mock_web_base_loader_class

        urls = ["https://site1.com", "https://site2.com"]
        result = web_loader.load_data(urls)

        assert len(result) == 2
        assert all(isinstance(doc, Document) for doc in result)
        assert result[0].text == "Content from site 1"
        assert result[1].text == "Content from site 2"
        assert result[0].extra_info == {"source": "https://site1.com"}
        assert result[1].extra_info == {"source": "https://site2.com"}

        assert mock_web_base_loader_class.call_count == 2
        mock_web_base_loader_class.assert_any_call(["https://site1.com"], header_template=headers)
        mock_web_base_loader_class.assert_any_call(["https://site2.com"], header_template=headers)

    def test_load_data_url_without_scheme(self, web_loader, mock_langchain_document):
        """Test loading data from URL without scheme (should add http://)."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [mock_langchain_document]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("example.com")

        assert len(result) == 1
        assert isinstance(result[0], Document)

        # Verify WebBaseLoader was called with http:// prefix
        mock_web_base_loader_class.assert_called_once_with(["http://example.com"], header_template=headers)

    def test_load_data_url_with_scheme(self, web_loader, mock_langchain_document):
        """Test loading data from URL with scheme (should not modify)."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [mock_langchain_document]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("https://example.com")

        assert len(result) == 1

        # Verify WebBaseLoader was called with original URL
        mock_web_base_loader_class.assert_called_once_with(["https://example.com"], header_template=headers)

    def test_load_data_multiple_documents_per_url(self, web_loader):
        """Test loading multiple documents from a single URL."""
        doc1 = MagicMock(spec=LCDocument)
        doc1.page_content = "First document content"
        doc1.metadata = {"source": "https://example.com", "section": "intro"}

        doc2 = MagicMock(spec=LCDocument)
        doc2.page_content = "Second document content"
        doc2.metadata = {"source": "https://example.com", "section": "main"}

        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [doc1, doc2]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("https://example.com")

        assert len(result) == 2
        assert result[0].text == "First document content"
        assert result[1].text == "Second document content"
        assert result[0].extra_info == {"source": "https://example.com", "section": "intro"}
        assert result[1].extra_info == {"source": "https://example.com", "section": "main"}


class TestWebLoaderErrorHandling:
    """Test WebLoader error handling."""

    @patch('application.parser.remote.web_loader.logging')
    def test_load_data_single_url_error(self, mock_logging, web_loader):
        """Test error handling for single URL that fails to load."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.side_effect = Exception("Network error")

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("https://invalid-url.com")

        assert result == []  # Should return empty list on error
        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://invalid-url.com" in error_call[0][0]
        assert error_call[1]["exc_info"] is True

    @patch('application.parser.remote.web_loader.logging')
    def test_load_data_partial_failure(self, mock_logging, web_loader):
        """Test partial failure - some URLs succeed, some fail."""
        doc1 = MagicMock(spec=LCDocument)
        doc1.page_content = "Success content"
        doc1.metadata = {"source": "https://good-url.com"}

        mock_loader_instance1 = MagicMock()
        mock_loader_instance1.load.return_value = [doc1]

        mock_loader_instance2 = MagicMock()
        mock_loader_instance2.load.side_effect = Exception("Network error")

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.side_effect = [mock_loader_instance1, mock_loader_instance2]

        web_loader.loader = mock_web_base_loader_class

        urls = ["https://good-url.com", "https://bad-url.com"]
        result = web_loader.load_data(urls)

        assert len(result) == 1  # Only successful URL should be in results
        assert result[0].text == "Success content"
        assert result[0].extra_info == {"source": "https://good-url.com"}

        mock_logging.error.assert_called_once()
        error_call = mock_logging.error.call_args
        assert "Error processing URL https://bad-url.com" in error_call[0][0]


class TestWebLoaderEdgeCases:
    """Test WebLoader edge cases."""

    def test_load_data_empty_list(self, web_loader):
        """Test loading data with empty URL list."""
        result = web_loader.load_data([])
        assert result == []

    def test_load_data_empty_response(self, web_loader):
        """Test loading data when WebBaseLoader returns empty list."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = []

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_data("https://empty-page.com")

        assert result == []

    def test_url_scheme_detection(self):
        """Test URL scheme detection logic."""
        # Test URLs with schemes
        assert urlparse("https://example.com").scheme == "https"
        assert urlparse("http://example.com").scheme == "http"
        assert urlparse("ftp://example.com").scheme == "ftp"

        # Test URLs without schemes
        assert urlparse("example.com").scheme == ""
        assert urlparse("www.example.com").scheme == ""


class TestWebLoaderIntegration:
    """Test WebLoader integration with base class."""

    def test_inherits_from_base_remote(self, web_loader):
        """Test that WebLoader inherits from BaseRemote."""
        from application.parser.remote.base import BaseRemote
        assert isinstance(web_loader, BaseRemote)

    def test_implements_load_data_method(self, web_loader):
        """Test that WebLoader implements required load_data method."""
        assert hasattr(web_loader, 'load_data')
        assert callable(web_loader.load_data)

    def test_load_langchain_documents_method(self, web_loader, mock_langchain_document):
        """Test inherited load_langchain_documents method."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [mock_langchain_document]

        mock_web_base_loader_class = MagicMock()
        mock_web_base_loader_class.return_value = mock_loader_instance

        web_loader.loader = mock_web_base_loader_class

        result = web_loader.load_langchain_documents(inputs="https://example.com")

        assert len(result) == 1
        assert isinstance(result[0], LCDocument)
        assert result[0].page_content == "Test web page content"
        assert result[0].metadata == {"source": "https://example.com", "title": "Test Page"}
