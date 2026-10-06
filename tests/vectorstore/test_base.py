from unittest.mock import Mock, patch

import pytest

from docsgpt.vectorstore.base import (
    BaseVectorStore,
    EmbeddingsSingleton,
    RemoteEmbeddings,
    _key_fingerprint,
    get_embeddings,
)

HF_MPNET = "huggingface_sentence-transformers/all-mpnet-base-v2"
LOCAL_MPNET = "/app/models/all-mpnet-base-v2"


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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @pytest.mark.parametrize("status", [401, 403])
    @patch("docsgpt.vectorstore.base.requests.post")
    def test_auth_error_logs_the_key_fingerprint_not_the_key(self, mock_post, status, caplog):
        """An auth failure is a configuration error, reported once, naming no secret."""
        import requests

        response = requests.Response()
        response.status_code = status
        response.url = "http://host/v1/embeddings"
        mock_post.return_value = response

        emb = RemoteEmbeddings("http://host", "m", api_key="sk-secret-value")
        with caplog.at_level("ERROR"), pytest.raises(requests.HTTPError):
            emb._embed("test")

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(errors) == 1
        message = errors[0].getMessage()
        assert str(status) in message
        assert _key_fingerprint("sk-secret-value") in message
        assert "sk-secret-value" not in message
        assert errors[0].event == "embeddings_auth_failed"

    @patch("docsgpt.vectorstore.base.requests.post")
    def test_server_error_is_not_reported_as_an_auth_error(self, mock_post, caplog):
        import requests

        response = requests.Response()
        response.status_code = 503
        response.url = "http://host/v1/embeddings"
        mock_post.return_value = response

        emb = RemoteEmbeddings("http://host", "m", api_key="sk-key")
        with caplog.at_level("ERROR"), pytest.raises(requests.HTTPError):
            emb._embed("test")

        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    def test_key_fingerprint_is_stable_and_not_the_key(self):
        assert _key_fingerprint(None) == "nokey"
        assert _key_fingerprint("") == "nokey"
        assert _key_fingerprint("abc") == _key_fingerprint("abc")
        assert _key_fingerprint("abc") != _key_fingerprint("abd")
        assert "abc" not in _key_fingerprint("abc")

    @patch("docsgpt.vectorstore.base.requests.post")
    def test_embed_raises_on_error_response(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {"error": "rate limit exceeded"}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="rate limit exceeded"):
            emb._embed("test")

    @patch("docsgpt.vectorstore.base.requests.post")
    def test_embed_raises_on_unexpected_format(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = {"unexpected": True}
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Unexpected response format"):
            emb._embed("test")

    @patch("docsgpt.vectorstore.base.requests.post")
    def test_embed_raises_on_non_dict_response(self, mock_post):
        mock_resp = Mock()
        mock_resp.json.return_value = [1, 2, 3]
        mock_resp.raise_for_status = Mock()
        mock_post.return_value = mock_resp

        emb = RemoteEmbeddings("http://host", "m")
        with pytest.raises(ValueError, match="Unexpected response format"):
            emb._embed("test")

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.requests.post")
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

    @patch("docsgpt.vectorstore.base.OpenAIEmbeddings")
    def test_get_instance_openai(self, mock_openai_cls):
        mock_instance = Mock()
        mock_openai_cls.return_value = mock_instance

        result = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        assert result is mock_instance

    @patch("docsgpt.vectorstore.base.OpenAIEmbeddings")
    def test_singleton_returns_same_instance(self, mock_openai_cls):
        mock_instance = Mock()
        mock_openai_cls.return_value = mock_instance

        r1 = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        r2 = EmbeddingsSingleton.get_instance("openai_text-embedding-ada-002")
        assert r1 is r2
        mock_openai_cls.assert_called_once()

    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_huggingface(self, mock_get_wrapper):
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = EmbeddingsSingleton.get_instance(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        assert result is mock_instance

    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_unknown_falls_back_to_wrapper(self, mock_get_wrapper):
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = EmbeddingsSingleton.get_instance("custom_model_name")
        mock_wrapper_cls.assert_called_once_with("custom_model_name")
        assert result is mock_instance

    @patch("docsgpt.vectorstore.base.settings")
    def test_get_instance_uses_remote_when_base_url_set(self, mock_settings):
        """Direct callers (GraphRAG, semantic chunking) must route to the
        remote embeddings API instead of loading a local model."""
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_KEY = "sk-remote"

        result = EmbeddingsSingleton.get_instance("embeddinggemma", "sk-remote")

        assert isinstance(result, RemoteEmbeddings)
        assert result.api_url == "http://remote:8080"
        assert result.model_name == "embeddinggemma"
        assert result.headers["Authorization"] == "Bearer sk-remote"

    @patch("docsgpt.vectorstore.base.settings")
    def test_get_instance_remote_falls_back_to_settings_key(self, mock_settings):
        """When no key is passed, the remote dispatch uses EMBEDDINGS_KEY."""
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_KEY = "sk-from-settings"

        result = EmbeddingsSingleton.get_instance("embeddinggemma")

        assert isinstance(result, RemoteEmbeddings)
        assert result.headers["Authorization"] == "Bearer sk-from-settings"


    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_hf_ignores_positional_key(
        self, mock_get_wrapper, mock_settings
    ):
        """A stray key must not reach the wrapper for a registered model.

        Registered models take their whole configuration from the registry, so
        a caller that passes ``settings.EMBEDDINGS_KEY`` positionally (as the
        vector stores do) must have it dropped rather than forwarded.
        """
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = EmbeddingsSingleton.get_instance(HF_MPNET, None)

        assert result is mock_instance
        # The configured name is passed through; the registry maps it to a repo.
        mock_wrapper_cls.assert_called_once_with(HF_MPNET)

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_get_instance_hf_ignores_keyword_args(
        self, mock_get_wrapper, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_wrapper_cls = Mock()
        mock_get_wrapper.return_value = mock_wrapper_cls

        EmbeddingsSingleton.get_instance(HF_MPNET, openai_api_key="sk-nope")

        mock_wrapper_cls.assert_called_once_with(HF_MPNET)


@pytest.mark.unit
class TestEmbeddingsCacheIsKeyedByApiKey:
    """A cached client must never serve a caller that holds a different key.

    The cache used to be keyed without the key, so the first caller's key won
    for the life of the process: a store built with the legacy ``"embeddings"``
    placeholder (a source delete) left every later retrieval sending
    ``Bearer embeddings`` and getting 401s.
    """

    def setup_method(self):
        EmbeddingsSingleton._instances = {}

    def teardown_method(self):
        EmbeddingsSingleton._instances = {}

    @patch("docsgpt.vectorstore.base.settings")
    def test_remote_client_not_shared_across_keys(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_KEY = "real"

        poisoned = get_embeddings("m", "embeddings")
        real = get_embeddings("m", "real")

        assert real is not poisoned
        assert real.headers["Authorization"] == "Bearer real"
        assert poisoned.headers["Authorization"] == "Bearer embeddings"

    @patch("docsgpt.vectorstore.base.settings")
    def test_remote_client_shared_for_same_key(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_KEY = "real"

        first = get_embeddings("m", "real")
        second = get_embeddings("m", "real")
        from_settings = get_embeddings("m")

        assert first is second
        assert from_settings is first

    @patch("docsgpt.vectorstore.base.settings")
    def test_remote_cache_key_does_not_contain_the_key(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_KEY = "sk-secret-value"

        get_embeddings("m")

        assert not any("sk-secret-value" in key for key in EmbeddingsSingleton._instances)

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.OpenAIEmbeddings")
    def test_openai_client_not_shared_across_keys(self, mock_openai_cls, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None
        mock_settings.EMBEDDINGS_DELEGATE_TO_WORKER = False
        mock_settings.EMBEDDINGS_KEY = "sk-real"
        mock_openai_cls.side_effect = lambda **kwargs: Mock(**kwargs)

        poisoned = get_embeddings("openai_text-embedding-ada-002", "embeddings")
        real = get_embeddings("openai_text-embedding-ada-002", "sk-real")
        again = get_embeddings("openai_text-embedding-ada-002")

        assert real is not poisoned
        assert real.openai_api_key == "sk-real"
        assert again is real
        assert mock_openai_cls.call_count == 2

    @patch("docsgpt.vectorstore.base.settings")
    def test_delegated_client_not_shared_across_keys(self, mock_settings):
        """The worker-local fallback of a delegated client embeds with its key."""
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_DELEGATE_TO_WORKER = True
        mock_settings.EMBEDDINGS_KEY = "sk-real"

        poisoned = get_embeddings("m", "embeddings")
        real = get_embeddings("m", "sk-real")

        assert real is not poisoned
        assert real.embeddings_key == "sk-real"
        assert get_embeddings("m", "sk-real") is real

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_local_model_cache_key_stays_the_model_name(self, mock_get_wrapper, mock_settings):
        """The boot hook evicts the local model by its bare name."""
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_KEY = "sk-ignored"
        mock_get_wrapper.return_value = Mock()

        get_embeddings(HF_MPNET, "sk-ignored")

        assert set(EmbeddingsSingleton._instances) == {HF_MPNET}


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

    @patch("docsgpt.vectorstore.base.settings")
    def test_is_azure_configured_true(self, mock_settings):
        mock_settings.OPENAI_API_BASE = "https://azure.openai.com"
        mock_settings.OPENAI_API_VERSION = "2023-05-15"
        mock_settings.AZURE_DEPLOYMENT_NAME = "my-deploy"

        store = ConcreteVectorStore()
        assert store.is_azure_configured()

    @patch("docsgpt.vectorstore.base.settings")
    def test_is_azure_configured_false(self, mock_settings):
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None

        store = ConcreteVectorStore()
        assert not store.is_azure_configured()

    @patch("docsgpt.vectorstore.base.settings")
    def test_get_embeddings_remote(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"

        store = ConcreteVectorStore()
        result = store._get_embeddings("model-name", "api-key")

        assert isinstance(result, RemoteEmbeddings)
        assert result.api_url == "http://remote:8080"

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
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

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
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

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
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

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_get_embeddings_registered_model_passes_configured_name(
        self, mock_get_instance, mock_settings
    ):
        """No bundled-path branch any more: the name goes straight through.

        FastEmbed resolves artifacts through its own cache (warmed in the
        image), so the old ``/app/models/...`` probe has no job to do.
        """
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )
        assert result is mock_emb
        mock_get_instance.assert_called_with(
            "huggingface_sentence-transformers/all-mpnet-base-v2"
        )

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_get_embeddings_generic(self, mock_get_instance, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_emb = Mock()
        mock_get_instance.return_value = mock_emb

        store = ConcreteVectorStore()
        result = store._get_embeddings("some_custom_embedding")
        assert result is mock_emb
        mock_get_instance.assert_called_with("some_custom_embedding")


@pytest.mark.unit
class TestSearchWithScoresDefault:
    def test_pairs_hits_with_none(self):
        """A store that reports no score still satisfies the contract, so the
        retriever never has to special-case it."""
        from docsgpt.vectorstore.base import BaseVectorStore

        class _Store(BaseVectorStore):
            def search(self, question, k=2, *args, **kwargs):
                return ["a", "b"]

            def add_texts(self, texts, metadatas=None, *args, **kwargs):
                return []

        store = _Store()
        assert store.score_kind is None
        assert store.search_with_scores("q", k=2) == [("a", None), ("b", None)]

    def test_handles_store_returning_none(self):
        from docsgpt.vectorstore.base import BaseVectorStore

        class _Store(BaseVectorStore):
            def search(self, question, k=2, *args, **kwargs):
                return None

            def add_texts(self, texts, metadatas=None, *args, **kwargs):
                return []

        assert _Store().search_with_scores("q") == []


# --- get_embeddings (the single resolver) ---


@pytest.mark.unit
class TestGetEmbeddingsResolver:
    """``get_embeddings`` is the one entry point every caller must use.

    Calling ``EmbeddingsSingleton.get_instance`` directly reproduces neither the
    bundled local-model path nor the OpenAI/Azure key handling.
    """

    def setup_method(self):
        EmbeddingsSingleton._instances = {}

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    @patch("os.path.exists", return_value=False)
    def test_defaults_from_settings_do_not_raise(
        self, _mock_exists, mock_get_wrapper, mock_settings
    ):
        """The default config (HF mpnet name, no key) must resolve, not crash."""
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_NAME = HF_MPNET
        mock_settings.EMBEDDINGS_KEY = None
        mock_wrapper_cls = Mock()
        mock_instance = Mock()
        mock_wrapper_cls.return_value = mock_instance
        mock_get_wrapper.return_value = mock_wrapper_cls

        result = get_embeddings()

        assert result is mock_instance
        assert set(EmbeddingsSingleton._instances) == {HF_MPNET}

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    @patch("os.path.exists", return_value=False)
    def test_shares_cache_entry_with_vectorstore_helper(
        self, _mock_exists, mock_get_wrapper, mock_settings
    ):
        """Same object, same cache key as the vector stores get — one model."""
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_NAME = HF_MPNET
        mock_settings.EMBEDDINGS_KEY = None
        mock_wrapper_cls = Mock()
        mock_wrapper_cls.return_value = Mock()
        mock_get_wrapper.return_value = mock_wrapper_cls

        store_result = ConcreteVectorStore()._get_embeddings(HF_MPNET, None)
        resolver_result = get_embeddings()

        assert resolver_result is store_result
        assert set(EmbeddingsSingleton._instances) == {HF_MPNET}
        mock_wrapper_cls.assert_called_once()

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base._get_embeddings_wrapper")
    def test_repeated_resolution_loads_one_model(
        self, mock_get_wrapper, mock_settings
    ):
        """A second call must not load a second copy of the model.

        The instance is keyed by the configured name. It used to be keyed by a
        bundled filesystem path when one happened to exist, which meant the
        same model could be cached twice under two keys.
        """
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_NAME = HF_MPNET
        mock_settings.EMBEDDINGS_KEY = None
        mock_wrapper_cls = Mock()
        mock_wrapper_cls.return_value = Mock()
        mock_get_wrapper.return_value = mock_wrapper_cls

        first = get_embeddings()
        second = get_embeddings()

        assert first is second
        assert set(EmbeddingsSingleton._instances) == {HF_MPNET}
        mock_wrapper_cls.assert_called_once_with(HF_MPNET)

    @patch("docsgpt.vectorstore.base.settings")
    def test_remote_when_base_url_configured(self, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = "http://remote:8080"
        mock_settings.EMBEDDINGS_NAME = HF_MPNET
        mock_settings.EMBEDDINGS_KEY = "sk-remote"

        result = get_embeddings()

        assert isinstance(result, RemoteEmbeddings)
        assert result.api_url == "http://remote:8080"
        assert result.model_name == HF_MPNET
        assert result.headers["Authorization"] == "Bearer sk-remote"

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_openai_passes_key(self, mock_get_instance, mock_settings):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None
        mock_settings.EMBEDDINGS_NAME = "openai_text-embedding-ada-002"
        mock_settings.EMBEDDINGS_KEY = "sk-from-settings"

        get_embeddings()

        mock_get_instance.assert_called_once_with(
            "openai_text-embedding-ada-002", openai_api_key="sk-from-settings"
        )

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_openai_azure_uses_deployment_name(
        self, mock_get_instance, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = "https://azure.openai.com"
        mock_settings.OPENAI_API_VERSION = "2023-05-15"
        mock_settings.AZURE_DEPLOYMENT_NAME = "deploy"
        mock_settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME = "embed-deploy"
        mock_settings.EMBEDDINGS_NAME = "openai_text-embedding-ada-002"
        mock_settings.EMBEDDINGS_KEY = "sk-key"

        get_embeddings()

        mock_get_instance.assert_called_once_with(
            "openai_text-embedding-ada-002", model="embed-deploy"
        )

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_openai_alias_also_reaches_the_azure_deployment(
        self, mock_get_instance, mock_settings
    ):
        """The registry accepts the bare alias, so the key handling must too.

        Matching on the canonical string alone sent the alias down the generic
        branch, where the deployment name is never passed and Azure answers
        every embed with DeploymentNotFound.
        """
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = "https://azure.openai.com"
        mock_settings.OPENAI_API_VERSION = "2023-05-15"
        mock_settings.AZURE_DEPLOYMENT_NAME = "deploy"
        mock_settings.AZURE_EMBEDDINGS_DEPLOYMENT_NAME = "embed-deploy"
        mock_settings.EMBEDDINGS_NAME = "text-embedding-ada-002"
        mock_settings.EMBEDDINGS_KEY = "sk-key"

        get_embeddings()

        mock_get_instance.assert_called_once_with(
            "text-embedding-ada-002", model="embed-deploy"
        )

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_openai_name_is_matched_case_insensitively(
        self, mock_get_instance, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.OPENAI_API_BASE = None
        mock_settings.OPENAI_API_VERSION = None
        mock_settings.AZURE_DEPLOYMENT_NAME = None
        mock_settings.EMBEDDINGS_NAME = "OpenAI_Text-Embedding-Ada-002"
        mock_settings.EMBEDDINGS_KEY = "sk-from-settings"

        get_embeddings()

        mock_get_instance.assert_called_once_with(
            "OpenAI_Text-Embedding-Ada-002", openai_api_key="sk-from-settings"
        )

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.EmbeddingsSingleton.get_instance")
    def test_explicit_arguments_win_over_settings(
        self, mock_get_instance, mock_settings
    ):
        mock_settings.EMBEDDINGS_BASE_URL = None
        mock_settings.EMBEDDINGS_NAME = HF_MPNET
        mock_settings.EMBEDDINGS_KEY = "sk-from-settings"

        get_embeddings("some_custom_embedding", "sk-explicit")

        mock_get_instance.assert_called_once_with("some_custom_embedding")

    @patch("docsgpt.vectorstore.base.settings")
    @patch("docsgpt.vectorstore.base.get_embeddings")
    def test_vectorstore_helper_delegates_to_resolver(
        self, mock_resolver, _mock_settings
    ):
        """``BaseVectorStore._get_embeddings`` is a thin delegate now."""
        sentinel = Mock()
        mock_resolver.return_value = sentinel

        result = ConcreteVectorStore()._get_embeddings("a-name", "a-key")

        assert result is sentinel
        mock_resolver.assert_called_once_with("a-name", "a-key")


class _RecordingStore(ConcreteVectorStore):
    """Store whose add/delete calls are recorded, for the update fallback."""

    def __init__(self, delete_result=True, delete_error=None):
        super().__init__()
        self.calls = []
        self._delete_result = delete_result
        self._delete_error = delete_error

    def add_chunk(self, text, metadata=None, *args, **kwargs):
        self.calls.append(("add", text, metadata))
        return "new-id"

    def delete_chunk(self, chunk_id, *args, **kwargs):
        self.calls.append(("delete", chunk_id))
        if chunk_id != "old-id":
            return True
        if self._delete_error is not None:
            raise self._delete_error
        return self._delete_result


@pytest.mark.unit
class TestBaseUpdateChunkFallback:
    def test_adds_then_deletes_and_returns_the_new_id(self):
        store = _RecordingStore()

        new_id = store.update_chunk("old-id", "new text", {"k": "v"})

        assert new_id == "new-id"
        assert store.calls == [("add", "new text", {"k": "v"}), ("delete", "old-id")]

    def test_false_delete_rolls_back_the_new_chunk_and_raises(self):
        store = _RecordingStore(delete_result=False)

        with pytest.raises(RuntimeError, match="old-id"):
            store.update_chunk("old-id", "new text", {})

        assert store.calls == [
            ("add", "new text", {}),
            ("delete", "old-id"),
            ("delete", "new-id"),
        ]

    def test_raising_delete_rolls_back_the_new_chunk_and_raises(self):
        store = _RecordingStore(delete_error=ConnectionError("milvus down"))

        with pytest.raises(RuntimeError, match="old-id") as excinfo:
            store.update_chunk("old-id", "new text", {})

        assert isinstance(excinfo.value.__cause__, ConnectionError)
        assert store.calls[-1] == ("delete", "new-id")

    def test_failed_rollback_still_raises_the_update_error(self, caplog):
        store = _RecordingStore(delete_result=False)
        real_delete = store.delete_chunk

        def delete(chunk_id, *args, **kwargs):
            if chunk_id == "new-id":
                store.calls.append(("delete", chunk_id))
                raise ConnectionError("rollback failed")
            return real_delete(chunk_id)

        store.delete_chunk = delete

        with caplog.at_level("ERROR"), pytest.raises(RuntimeError, match="old-id"):
            store.update_chunk("old-id", "new text", {})

        assert ("delete", "new-id") in store.calls
        assert "new-id" in caplog.text

    def test_failed_add_skips_the_delete(self):
        store = _RecordingStore()
        store.add_chunk = Mock(side_effect=RuntimeError("embed down"))

        with pytest.raises(RuntimeError):
            store.update_chunk("old-id", "new text", {})

        assert ("delete", "old-id") not in store.calls

    def test_milvus_keeps_the_default(self):
        """Milvus has no in-place update here; it re-adds under a new id."""
        from docsgpt.vectorstore.milvus import MilvusStore

        assert MilvusStore.update_chunk is BaseVectorStore.update_chunk


class _ChunkListStore(ConcreteVectorStore):
    def __init__(self, chunks):
        super().__init__()
        self._chunks = chunks

    def get_chunks(self, *args, **kwargs):
        return self._chunks


@pytest.mark.unit
class TestBaseGetChunkByKey:
    """The default lookup hashes the source's chunks until one matches."""

    def test_returns_the_chunk_whose_text_hashes_to_the_key(self):
        from docsgpt.retriever.labels import chunk_key

        store = _ChunkListStore([
            {"doc_id": "1", "text": "first", "metadata": {}},
            {"doc_id": "2", "text": "second", "metadata": {"title": "b"}},
        ])
        found = store.get_chunk_by_key(chunk_key("second"))
        assert found == {"doc_id": "2", "text": "second", "metadata": {"title": "b"}}

    def test_first_copy_wins_for_duplicate_text(self):
        from docsgpt.retriever.labels import chunk_key

        store = _ChunkListStore([
            {"doc_id": "1", "text": "boilerplate", "metadata": {}},
            {"doc_id": "2", "text": "boilerplate", "metadata": {}},
        ])
        assert store.get_chunk_by_key(chunk_key("boilerplate"))["doc_id"] == "1"

    def test_no_match_is_none(self):
        assert _ChunkListStore([{"doc_id": "1", "text": "x"}]).get_chunk_by_key("0" * 32) is None

    def test_a_store_without_get_chunks_cannot_look_up(self):
        # Elasticsearch has no ``get_chunks``; the base one returns None,
        # which must not read as "the chunk is gone".
        with pytest.raises(NotImplementedError):
            ConcreteVectorStore().get_chunk_by_key("0" * 32)

    def test_a_scan_error_propagates(self):
        class _Down(ConcreteVectorStore):
            def _scan_chunks(self):
                raise RuntimeError("down")

        with pytest.raises(RuntimeError):
            _Down().get_chunk_by_key("0" * 32)

    def test_a_key_miss_falls_back_to_the_excerpt_in_the_same_scan(self):
        store = _ChunkListStore([
            {"doc_id": "1", "text": "Other clause", "metadata": {}},
            {"doc_id": "2", "text": "Late Pickup fees apply after 6pm", "metadata": {}},
        ])
        found = store.get_chunk_by_key("0" * 32, excerpt="late pickup fees")
        assert found["doc_id"] == "2"

    def test_the_key_wins_over_an_earlier_excerpt_match(self):
        from docsgpt.retriever.labels import chunk_key

        store = _ChunkListStore([
            {"doc_id": "1", "text": "Late pickup, older copy", "metadata": {}},
            {"doc_id": "2", "text": "Late pickup", "metadata": {}},
        ])
        assert store.get_chunk_by_key(chunk_key("Late pickup"), excerpt="Late pickup")["doc_id"] == "2"

    def test_a_blank_excerpt_matches_nothing(self):
        store = _ChunkListStore([{"doc_id": "1", "text": "x", "metadata": {}}])
        assert store.get_chunk_by_key("0" * 32, excerpt="   ") is None
