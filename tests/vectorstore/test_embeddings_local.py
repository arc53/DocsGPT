"""Local embeddings run through FastEmbed, configured from the model registry."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from application.vectorstore import embeddings_local
from application.vectorstore.embeddings_local import EmbeddingsWrapper
from application.vectorstore.model_registry import GRANITE_97M, MPNET


@pytest.fixture(autouse=True)
def _clear_registration():
    """``add_custom_model`` writes to a FastEmbed global; keep tests isolated."""
    embeddings_local._registered.clear()
    yield
    embeddings_local._registered.clear()


@pytest.fixture
def fake_fastembed():
    """Patch FastEmbed so no model is downloaded or run."""
    text_embedding = MagicMock()
    instance = MagicMock()
    instance.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
    text_embedding.return_value = instance
    with patch("fastembed.TextEmbedding", text_embedding):
        yield text_embedding, instance


class TestRegistryDrivenLoading:
    def test_registered_model_loads_by_repo_not_by_configured_name(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        wrapper = EmbeddingsWrapper(MPNET.name)
        assert text_embedding.call_args.kwargs["model_name"] == MPNET.repo
        assert wrapper.dimension == MPNET.dimension

    def test_legacy_alias_resolves_to_the_same_model(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        EmbeddingsWrapper("huggingface_sentence-transformers-all-mpnet-base-v2")
        assert text_embedding.call_args.kwargs["model_name"] == MPNET.repo

    def test_dimension_comes_from_registry_without_running_the_model(self, fake_fastembed):
        _, instance = fake_fastembed
        wrapper = EmbeddingsWrapper(GRANITE_97M.name)
        assert wrapper.dimension == 384
        instance.embed.assert_not_called()

    def test_unknown_model_is_treated_as_a_hf_repo(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        wrapper = EmbeddingsWrapper("some-org/custom-embedder")
        assert text_embedding.call_args.kwargs["model_name"] == "some-org/custom-embedder"
        # No registry entry means no known width, so it must be probed.
        assert wrapper.dimension == 3

    def test_load_failure_names_the_model_and_the_known_ones(self):
        with patch("fastembed.TextEmbedding", side_effect=OSError("no such repo")):
            with pytest.raises(RuntimeError) as excinfo:
                EmbeddingsWrapper("broken/model")
        message = str(excinfo.value)
        assert "broken/model" in message
        assert MPNET.name in message


class TestSettingsPassthrough:
    def test_threads_forwarded_when_configured(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        with patch.object(embeddings_local.settings, "EMBEDDINGS_THREADS", 2, create=True):
            EmbeddingsWrapper(MPNET.name)
        assert text_embedding.call_args.kwargs["threads"] == 2

    def test_threads_omitted_when_unset(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        with patch.object(embeddings_local.settings, "EMBEDDINGS_THREADS", None, create=True):
            EmbeddingsWrapper(MPNET.name)
        assert "threads" not in text_embedding.call_args.kwargs

    def test_cache_dir_forwarded_when_configured(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        with patch.object(embeddings_local.settings, "EMBEDDINGS_CACHE_DIR", "/models", create=True):
            EmbeddingsWrapper(MPNET.name)
        assert text_embedding.call_args.kwargs["cache_dir"] == "/models"


class TestEmbedding:
    def test_embed_documents_returns_plain_lists(self, fake_fastembed):
        _, instance = fake_fastembed
        instance.embed.return_value = iter([np.array([1.0, 2.0]), np.array([3.0, 4.0])])
        wrapper = EmbeddingsWrapper(MPNET.name)
        assert wrapper.embed_documents(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]

    def test_embed_documents_short_circuits_on_empty_input(self, fake_fastembed):
        _, instance = fake_fastembed
        wrapper = EmbeddingsWrapper(MPNET.name)
        instance.embed.reset_mock()
        assert wrapper.embed_documents([]) == []
        instance.embed.assert_not_called()

    def test_embed_query_returns_a_single_vector(self, fake_fastembed):
        _, instance = fake_fastembed
        instance.embed.return_value = iter([np.array([0.5, 0.6])])
        wrapper = EmbeddingsWrapper(MPNET.name)
        assert wrapper.embed_query("hello") == [0.5, 0.6]

    def test_call_dispatches_on_input_type(self, fake_fastembed):
        _, instance = fake_fastembed
        wrapper = EmbeddingsWrapper(MPNET.name)
        instance.embed.return_value = iter([np.array([1.0])])
        assert wrapper("text") == [1.0]
        instance.embed.return_value = iter([np.array([1.0]), np.array([2.0])])
        assert wrapper(["a", "b"]) == [[1.0], [2.0]]

    def test_call_rejects_other_types(self, fake_fastembed):
        wrapper = EmbeddingsWrapper(MPNET.name)
        with pytest.raises(ValueError):
            wrapper(42)


class TestRegistrationIsIdempotent:
    def test_model_registered_once_per_process(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        EmbeddingsWrapper(MPNET.name)
        EmbeddingsWrapper(MPNET.name)
        assert text_embedding.add_custom_model.call_count == 1


class TestLengthSortedBatching:
    """Grouping by length is a throughput/memory win, but order is a contract."""

    def _wrapper(self, fake_fastembed, batch_size):
        _, instance = fake_fastembed
        wrapper = EmbeddingsWrapper(MPNET.name)
        instance.embed.side_effect = lambda texts, batch_size=None: iter(
            [np.array([float(len(t))]) for t in texts]
        )
        return wrapper, instance

    def test_output_order_matches_input_order(self, fake_fastembed):
        with patch.object(embeddings_local.settings, "EMBEDDINGS_BATCH_SIZE", 2, create=True):
            wrapper, _ = self._wrapper(fake_fastembed, 2)
            texts = ["dddd", "a", "ccc", "bb", "eeeee"]
            out = wrapper.embed_documents(texts)
        # Each stub vector encodes its own text length, so a reordered result
        # is immediately visible.
        assert out == [[4.0], [1.0], [3.0], [2.0], [5.0]]

    def test_inputs_are_grouped_by_length_before_batching(self, fake_fastembed):
        with patch.object(embeddings_local.settings, "EMBEDDINGS_BATCH_SIZE", 2, create=True):
            wrapper, instance = self._wrapper(fake_fastembed, 2)
            wrapper.embed_documents(["dddd", "a", "ccc", "bb", "eeeee"])
        sent = instance.embed.call_args.args[0]
        assert [len(t) for t in sent] == [1, 2, 3, 4, 5]

    def test_single_batch_is_not_reordered(self, fake_fastembed):
        with patch.object(embeddings_local.settings, "EMBEDDINGS_BATCH_SIZE", 32, create=True):
            wrapper, instance = self._wrapper(fake_fastembed, 32)
            texts = ["dddd", "a", "ccc"]
            out = wrapper.embed_documents(texts)
        assert instance.embed.call_args.args[0] == texts
        assert out == [[4.0], [1.0], [3.0]]

    def test_duplicate_texts_are_handled(self, fake_fastembed):
        with patch.object(embeddings_local.settings, "EMBEDDINGS_BATCH_SIZE", 2, create=True):
            wrapper, _ = self._wrapper(fake_fastembed, 2)
            out = wrapper.embed_documents(["aa", "b", "aa", "ccc"])
        assert out == [[2.0], [1.0], [2.0], [3.0]]
