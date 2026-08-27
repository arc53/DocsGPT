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


@pytest.fixture(autouse=True)
def _no_hub_reads():
    """Keep unit tests off the network.

    ``_spec_for`` now asks a repository how it pools; without this every test
    naming an unregistered model would reach the Hugging Face hub. ``None`` is
    the "declares nothing" answer, which is the behaviour these tests were
    written against. Tests that exercise the metadata patch it themselves.
    """
    with patch.object(embeddings_local, "_read_repo_json", return_value=None):
        yield


@pytest.fixture
def fake_fastembed():
    """Patch FastEmbed so no model is downloaded or run."""
    text_embedding = MagicMock()
    instance = MagicMock()
    instance.embed.return_value = iter([np.array([0.1, 0.2, 0.3])])
    text_embedding.return_value = instance
    # Registration checks this before calling ``add_custom_model``; an empty
    # list means "no built-in collides", which is the case for every name in
    # our registry.
    text_embedding.list_supported_models.return_value = []
    with patch("fastembed.TextEmbedding", text_embedding):
        yield text_embedding, instance


class TestBuiltinModelRegistration:
    """FastEmbed ships ~30 models of its own and refuses to re-register any of
    them, so registering unconditionally broke every natively-supported name."""

    def test_builtin_name_is_not_re_registered(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        text_embedding.list_supported_models.return_value = [
            {"model": "BAAI/bge-small-en-v1.5"}
        ]
        EmbeddingsWrapper("BAAI/bge-small-en-v1.5")
        text_embedding.add_custom_model.assert_not_called()
        assert text_embedding.call_args.kwargs["model_name"] == "BAAI/bge-small-en-v1.5"

    def test_builtin_match_ignores_case(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        text_embedding.list_supported_models.return_value = [
            {"model": "baai/BGE-Small-EN-v1.5"}
        ]
        EmbeddingsWrapper("BAAI/bge-small-en-v1.5")
        text_embedding.add_custom_model.assert_not_called()

    def test_unknown_name_is_still_registered(self, fake_fastembed):
        text_embedding, _ = fake_fastembed
        text_embedding.list_supported_models.return_value = [
            {"model": "BAAI/bge-small-en-v1.5"}
        ]
        EmbeddingsWrapper("some-org/custom-embedder")
        text_embedding.add_custom_model.assert_called_once()

    def test_real_fastembed_accepts_its_own_builtin(self):
        """Runs against the installed FastEmbed, not the MagicMock.

        The mocked tests above cannot catch this: the failure was
        ``add_custom_model`` raising, and a MagicMock never raises.
        """
        fastembed = pytest.importorskip("fastembed")
        builtins = [m["model"] for m in fastembed.TextEmbedding.list_supported_models()]
        assert builtins, "expected FastEmbed to ship built-in models"
        spec = embeddings_local._spec_for(builtins[0])
        # Must not raise ValueError("... is already registered ...").
        embeddings_local._register(spec)


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


class TestTokenizerPadding:
    """A fixed padding width in ``tokenizer.json`` makes mixed batches ragged.

    FastEmbed calls ``enable_padding`` only when the tokenizer declares none,
    so mpnet's fixed ``length: 128`` survives loading. Any batch mixing an
    input longer than 128 tokens with a shorter one then produces rows of
    different widths and ONNX rejects the tensor.
    """

    def _tokenizer(self, padding):
        tokenizer = MagicMock()
        tokenizer.padding = padding
        return tokenizer

    def test_fixed_width_padding_is_reset_to_batch_longest(self, fake_fastembed):
        _, instance = fake_fastembed
        tokenizer = self._tokenizer(
            {
                "length": 128,
                "pad_id": 1,
                "pad_token": "<pad>",
                "pad_type_id": 0,
                "direction": "right",
                "pad_to_multiple_of": None,
            }
        )
        instance.model.tokenizer = tokenizer

        EmbeddingsWrapper(MPNET.name)

        kwargs = tokenizer.enable_padding.call_args.kwargs
        assert kwargs["length"] is None, "padding must follow the longest input"
        # The model's own pad token must survive the reset.
        assert kwargs["pad_id"] == 1
        assert kwargs["pad_token"] == "<pad>"

    def test_dynamic_padding_is_left_alone(self, fake_fastembed):
        _, instance = fake_fastembed
        tokenizer = self._tokenizer({"length": None, "pad_id": 0, "pad_token": "<pad>"})
        instance.model.tokenizer = tokenizer

        EmbeddingsWrapper(GRANITE_97M.name)

        tokenizer.enable_padding.assert_not_called()

    def test_tokenizer_that_cannot_be_reached_is_not_fatal(self, fake_fastembed):
        _, instance = fake_fastembed
        instance.model = None
        EmbeddingsWrapper(GRANITE_97M.name)


def _repo_json(pooling_file, modules_file):
    """Stub ``_read_repo_json`` returning canned repository metadata."""

    def read(repo, filename):
        return pooling_file if filename == embeddings_local._POOLING_CONFIG else modules_file

    return read


class TestPoolingReadFromTheRepository:
    """A model's pooling is a fact its repository states, not a default.

    Assuming mean pooling for a CLS model returns vectors at cosine ~0.95 to
    the correct ones: no error, no dimension mismatch, just quietly worse
    retrieval. These cover the shapes seen on the hub.
    """

    def test_cls_pooling_is_read_rather_than_assumed(self):
        with patch.object(
            embeddings_local,
            "_read_repo_json",
            _repo_json(
                {"pooling_mode_cls_token": True, "word_embedding_dimension": 384},
                [{"type": "sentence_transformers.models.Transformer"},
                 {"type": "sentence_transformers.models.Pooling"},
                 {"type": "sentence_transformers.models.Normalize"}],
            ),
        ):
            spec = embeddings_local._spec_for("BAAI/bge-small-en-v1.5")
        assert spec.pooling == "cls"
        assert spec.normalize is True
        # Declared width, so no probe run is needed to learn it.
        assert spec.dimension == 384

    def test_missing_normalize_module_means_unnormalised(self):
        """multi-qa-mpnet-base-dot-v1 is trained on unnormalised vectors."""
        with patch.object(
            embeddings_local,
            "_read_repo_json",
            _repo_json(
                {"pooling_mode_cls_token": True, "word_embedding_dimension": 768},
                [{"type": "sentence_transformers.models.Transformer"},
                 {"type": "sentence_transformers.models.Pooling"}],
            ),
        ):
            spec = embeddings_local._spec_for("sentence-transformers/multi-qa-mpnet-base-dot-v1")
        assert spec.pooling == "cls"
        assert spec.normalize is False

    def test_dense_projection_head_is_refused(self):
        """FastEmbed would skip the projection and emit the wrong vectors."""
        with patch.object(
            embeddings_local,
            "_read_repo_json",
            _repo_json(
                {"pooling_mode_cls_token": True, "word_embedding_dimension": 768},
                [{"type": "sentence_transformers.models.Transformer"},
                 {"type": "sentence_transformers.models.Pooling"},
                 {"type": "sentence_transformers.models.Dense"},
                 {"type": "sentence_transformers.models.Normalize"}],
            ),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                embeddings_local._spec_for("sentence-transformers/LaBSE")
        message = str(excinfo.value)
        assert "LaBSE" in message
        assert "Dense" in message

    def test_unsupported_pooling_mode_falls_back_rather_than_lying(self):
        with patch.object(
            embeddings_local,
            "_read_repo_json",
            _repo_json({"pooling_mode_max_tokens": True}, []),
        ):
            spec = embeddings_local._spec_for("some-org/max-pooled")
        assert spec.pooling == embeddings_local._FALLBACK_POOLING
        assert spec.dimension == 0

    def test_repository_without_metadata_keeps_the_assumption(self):
        spec = embeddings_local._spec_for("some-org/plain-onnx-export")
        assert spec.pooling == embeddings_local._FALLBACK_POOLING
        assert spec.normalize is True
        assert spec.dimension == 0

    def test_registry_wins_over_the_repository(self):
        """A described model is never re-read; the registry is the answer."""
        read = MagicMock()
        with patch.object(embeddings_local, "_read_repo_json", read):
            spec = embeddings_local._spec_for(MPNET.name)
        assert spec is MPNET
        read.assert_not_called()


class TestPoolingOverrides:
    def test_settings_override_what_the_repository_declares(self):
        with patch.object(
            embeddings_local,
            "_read_repo_json",
            _repo_json(
                {"pooling_mode_mean_tokens": True, "word_embedding_dimension": 768},
                [{"type": "sentence_transformers.models.Normalize"}],
            ),
        ):
            with patch.object(embeddings_local.settings, "EMBEDDINGS_POOLING", "cls"), \
                 patch.object(embeddings_local.settings, "EMBEDDINGS_NORMALIZE", False):
                spec = embeddings_local._spec_for("some-org/mislabelled")
        assert spec.pooling == "cls"
        assert spec.normalize is False

    def test_a_meaningless_override_is_ignored(self):
        with patch.object(embeddings_local.settings, "EMBEDDINGS_POOLING", "banana"):
            spec = embeddings_local._spec_for("some-org/plain-onnx-export")
        assert spec.pooling == embeddings_local._FALLBACK_POOLING
