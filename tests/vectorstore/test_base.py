import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from application.vectorstore.base import (
    BaseVectorStore,
    EmbeddingsSingleton,
    RemoteEmbeddings,
)


# --- RemoteEmbeddings ---


@pytest.mark.unit
class TestRemoteEmbeddings:
    def test_init_sets_url_and_headers(self):
        emb = RemoteEmbeddings(
            api_url="http://localhost:8080/", model_name="model-v1", api_key="sk-key"
        )
        assert emb.api_url == "http://localhost:8080"
        assert emb.model_name == "model-v1"
        assert emb.headers["Authorization"] == "Bearer sk-key"

    def test_init_no_api_key(self):
        emb = RemoteEmbeddings(api_url="http://host", model_name="m")
        assert "Authorization" not in emb.headers

    @patch("application.vectorstore.base.requests.post")
    def test_embed_sends_correct_payload(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2]}]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "model-v1")
        result = emb._embed("test input")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["input"] == "test input"
        assert call_kwargs[1]["json"]["model"] == "model-v1"
        assert result == [[0.1, 0.2]]

    @patch("application.vectorstore.base.requests.post")
    def test_embed_sorts_by_index(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        result = emb._embed(["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch("application.vectorstore.base.requests.post")
    def test_embed_raises_on_error_response(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {"error": "rate limit exceeded"}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="rate limit exceeded"):
            emb._embed("test")

    @patch("application.vectorstore.base.requests.post")
    def test_embed_raises_on_unexpected_format(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {"unexpected": True}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Unexpected response format"):
            emb._embed("test")

    @patch("application.vectorstore.base.requests.post")
    def test_embed_raises_on_non_dict_response(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = [1, 2, 3]
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Unexpected response format"):
            emb._embed("test")

    @patch("application.vectorstore.base.requests.post")
    def test_embed_query(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        emb.dimension = None  # Reset so it gets set from response
        result = emb.embed_query("hello")
        assert result == [0.1, 0.2, 0.3]
        assert emb.dimension == 3

    @patch("application.vectorstore.base.requests.post")
    def test_embed_query_raises_on_bad_structure(self, mock_post):
        mock_resp = Mock()
        # Return multiple embeddings for a single query
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1]},
                {"index": 1, "embedding": [0.2]},
            ]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Unexpected result structure"):
            emb.embed_query("hello")

    @patch("application.vectorstore.base.requests.post")
    def test_embed_documents(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        emb.dimension = None  # Reset so it gets set from response
        result = emb.embed_documents(["doc1", "doc2"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        assert emb.dimension == 2

    def test_embed_documents_empty(self):
        emb = RemoteEmbeddings("http://host", "m")
        assert emb.embed_documents([]) == []

    @patch("application.vectorstore.base.requests.post")
    def test_call_with_string(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.5]}]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        result = emb("hello")
        assert result == [0.5]

    @patch("application.vectorstore.base.requests.post")
    def test_call_with_list(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.5]}]
        }
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        result = emb(["hello"])
        assert result == [[0.5]]

    def test_call_with_invalid_type(self):
        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Input must be a string or a list"):
            emb(123)


# --- EmbeddingsSingleton ---


@pytest.mark.unit
class TestEmbeddingsSingleton:
    def setup_method(self):
        EmbeddingsSingleton._instances = {}

    @patch("application.vectorstore.base.OpenAIEmbeddings")
    def test_get_instance_openai(self, mock_openai_cls):
        mock_instance = Mock()
        mock_openai_cls.return_value = mock_instance

        result = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        assert result is mock_instance

    @patch("application.vectorstore.base.OpenAIEmbeddings")
    def test_singleton_returns_same_instance(self, mock_openai_cls):
        mock_instance = Mock()
        mock_openai_cls.return_value = mock_instance

        r1 = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        r2 = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        assert r1 is r2
        mock_openai_cls.assert_called_once()

    @patch("application.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_huggingface(self, mock_get_wrapper):
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = EmbeddingsSingleton.get_instance(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        assert result is mock_instance

    @patch("application.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_unknown_falls_back_to_wrapper(self, mock_get_wrapper):
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = EmbeddingsSingleton.get_instance("custom_model_name")
        mock_wrapper_cls.assert_called_once_with("custom_model_name")
        assert result is mock_instance


# --- BaseVectorStore ---


class ConcreteVectorStore(BaseVectorStore):
    """Concrete implementation for testing base class methods."""

    def search(self, *args, **kwargs):
        return []

    def add_texts(self, texts, metadatas=None, *args, **kwargs):
        return []


@pytest.mark.unit
class TestBaseVectorStore:
    def setup_method(self):
        EmbeddingsSingleton._instances = {}

    def test_default_methods_are_noop(self):
        store = ConcreteVectorStore()
        assert store.delete_index() is None
        assert store.save_local() is None
        assert store.get_chunks() is None
        assert store.add_chunk("text") is None
        assert store.delete_chunk("id") is None

    @patch("application.vectorstore.base.settings")
    def test_is_azure_configured_true(self, mock_settings):
        mock_settings.OPENAI_API_BASE = "https://azure.openai.com"
        mock_settings.OPENAI_API_VERSION = "2023-05-15"
        mock_settings.AZURE_DEPLOYMENT_NAME = "my-deploy"

        store = ConcreteVectorStore()
        assert store.is_azure_configured()

    @patch("application.vectorstore.base.settings")
    def test_is_azure_configured_false(self, mock_settings):
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None

        store = ConcreteVectorStore()
        assert not store.is_azure_configured()

    @patch("application.vectorstore.base.settings")
    def test_get_embeddings_remote(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"

        store = ConcreteVectorStore()
        result = store._get_embeddings("model-name", "api-key")

        assert isinstance(result, RemoteEmbeddings)
        assert result.api_url == "http://remote:8080"

    @patch("application.vectorstore.base.settings")
    @patch("application.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_get_embeddings_openai(self, mock_get_instance, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None

        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings("openai_text-embedding-ada-002", "sk-key")
        assert result is mock_emb

    @patch("application.vectorstore.base.settings")
    @patch("application.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_get_embeddings_openai_azure(self, mock_get_instance, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = "https://azure.openai.com"
        mock_settings.OPENAI_API_VERSION = "2023-05-15"
        mock_settings.AZURE_DEPLOYMENT_NAME = "deploy"
        mock_settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME = "embed-deploy"

        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings("openai_text-embedding-ada-002", "sk-key")
        assert result is mock_emb

    @patch("application.vectorstore.base.settings")
    @patch("application.vectorstore.base.EmbeddingsSingleton.get_instance")
    @patch("os.path.exists", return_value=False)
    def test_get_embeddings_huggingface_no_local_model(
        self, mock_exists, mock_get_instance, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        assert result is mock_emb

    @patch("application.vectorstore.base.settings")
    @patch("application.vectorstore.base.EmbeddingsSingleton.get_instance")
    @patch("os.path.exists")
    def test_get_embeddings_huggingface_local_model(
        self, mock_exists, mock_get_instance, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_exists.side_effect = lambda p: p == "/app/models/all-mpnet-base-v2"
        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        assert result is mock_emb
        mock_get_instance.assert_called_with("/app/models/all-mpnet-base-v2")

    @patch("application.vectorstore.base.settings")
    @patch("application.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_get_embeddings_generic(self, mock_get_instance, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings("some_custom_embedding")
        assert result is mock_emb
        mock_get_instance.assert_called_with("some_custom_embedding")
