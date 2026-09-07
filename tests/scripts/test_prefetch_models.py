"""Model pre-fetching, which the Docker build runs to bake artifacts in."""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.scripts import prefetch_models
from docsgpt.vectorstore.model_registry import GRANITE_311M, MPNET, OPENAI_ADA_002


@pytest.fixture
def fake_fastembed():
    """Stand in for FastEmbed so nothing is downloaded."""
    text_embedding = MagicMock()
    pooling = types.SimpleNamespace(CLS="CLS", MEAN="MEAN")
    module = types.ModuleType("fastembed")
    module.TextEmbedding = text_embedding
    desc = types.ModuleType("fastembed.common.model_description")
    desc.PoolingType = pooling
    desc.ModelSource = lambda hf=None: {"hf": hf}
    with patch.dict(
        sys.modules,
        {"fastembed": module, "fastembed.common.model_description": desc},
    ):
        yield text_embedding


class TestPrefetch:
    def test_defaults_cover_legacy_and_new_install(self):
        """An upgraded image must still serve mpnet; a new one needs granite."""
        assert MPNET.name in prefetch_models.DEFAULT_MODELS
        assert GRANITE_311M.name in prefetch_models.DEFAULT_MODELS

    def test_fetches_named_models(self, fake_fastembed):
        fetched = prefetch_models.prefetch([GRANITE_311M.name])
        assert fetched == [GRANITE_311M.repo]
        assert fake_fastembed.call_args.kwargs["model_name"] == GRANITE_311M.repo

    def test_registers_with_registry_pooling_and_dim(self, fake_fastembed):
        prefetch_models.prefetch([GRANITE_311M.name])
        kwargs = fake_fastembed.add_custom_model.call_args.kwargs
        assert kwargs["model"] == GRANITE_311M.repo
        assert kwargs["pooling"] == "CLS"
        assert kwargs["dim"] == GRANITE_311M.dimension
        assert kwargs["model_file"] == GRANITE_311M.onnx_file

    def test_mean_pooled_model_registers_as_mean(self, fake_fastembed):
        prefetch_models.prefetch([MPNET.name])
        assert fake_fastembed.add_custom_model.call_args.kwargs["pooling"] == "MEAN"

    def test_aliases_resolve(self, fake_fastembed):
        assert prefetch_models.prefetch(["granite-311m"]) == [GRANITE_311M.repo]

    def test_cache_dir_is_forwarded(self, fake_fastembed):
        prefetch_models.prefetch([MPNET.name], cache_dir="/models")
        assert fake_fastembed.call_args.kwargs["cache_dir"] == "/models"

    def test_cache_dir_omitted_when_absent(self, fake_fastembed):
        prefetch_models.prefetch([MPNET.name])
        assert "cache_dir" not in fake_fastembed.call_args.kwargs

    def test_remote_only_model_is_skipped(self, fake_fastembed):
        """OpenAI embeddings have no local artifacts to cache."""
        assert prefetch_models.prefetch([OPENAI_ADA_002.name]) == []
        fake_fastembed.assert_not_called()

    def test_unknown_model_fails_loudly(self, fake_fastembed):
        """A silent skip at build time is a download at run time, offline."""
        with pytest.raises(SystemExit) as excinfo:
            prefetch_models.prefetch(["nope/nope"])
        assert "nope/nope" in str(excinfo.value)
        assert MPNET.name in str(excinfo.value)

    def test_several_models_in_one_run(self, fake_fastembed):
        fetched = prefetch_models.prefetch([MPNET.name, GRANITE_311M.name])
        assert fetched == [MPNET.repo, GRANITE_311M.repo]


class TestMain:
    def test_no_args_fetches_the_defaults(self, fake_fastembed):
        with patch.object(prefetch_models, "prefetch", return_value=[]) as spy:
            assert prefetch_models.main([]) == 0
        assert spy.call_args.args[0] == list(prefetch_models.DEFAULT_MODELS)

    def test_explicit_args_override_the_defaults(self, fake_fastembed):
        with patch.object(prefetch_models, "prefetch", return_value=[]) as spy:
            prefetch_models.main(["granite-97m"])
        assert spy.call_args.args[0] == ["granite-97m"]

    def test_cache_dir_read_from_environment(self, fake_fastembed, monkeypatch):
        monkeypatch.setenv("EMBEDDINGS_CACHE_DIR", "/app/models")
        with patch.object(prefetch_models, "prefetch", return_value=[]) as spy:
            prefetch_models.main(["granite-97m"])
        assert spy.call_args.args[1] == "/app/models"


class TestPrefetchTiktoken:
    def test_warms_every_listed_encoding(self):
        """The image sets TIKTOKEN_CACHE_DIR; warming fills it at build time."""
        fake = MagicMock()
        module = types.ModuleType("tiktoken")
        module.get_encoding = fake
        with patch.dict(sys.modules, {"tiktoken": module}):
            fetched = prefetch_models.prefetch_tiktoken()
        assert fetched == list(prefetch_models.TIKTOKEN_ENCODINGS)
        assert [c.args[0] for c in fake.call_args_list] == list(prefetch_models.TIKTOKEN_ENCODINGS)

    def test_cl100k_is_the_encoding_token_counting_uses(self):
        assert "cl100k_base" in prefetch_models.TIKTOKEN_ENCODINGS
