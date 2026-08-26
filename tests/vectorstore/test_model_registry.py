"""The registry is the single source of truth for embedding-model facts."""

import pytest

from application.vectorstore import model_registry as reg


class TestResolve:
    def test_resolves_canonical_name(self):
        assert reg.resolve(reg.MPNET.name) is reg.MPNET

    @pytest.mark.parametrize(
        "alias",
        [
            "huggingface_sentence-transformers-all-mpnet-base-v2",
            "sentence-transformers/all-mpnet-base-v2",
            "all-mpnet-base-v2",
        ],
    )
    def test_resolves_legacy_spellings_of_mpnet(self, alias):
        """Every spelling the old factory dict accepted must still work."""
        assert reg.resolve(alias) is reg.MPNET

    def test_resolution_is_case_insensitive_and_trims(self):
        assert reg.resolve("  GRANITE-311M  ") is reg.GRANITE_311M

    def test_unknown_name_is_none_not_an_error(self):
        """Unknown names are a valid configuration: an arbitrary HF repo."""
        assert reg.resolve("some-org/some-model") is None

    def test_empty_and_none_resolve_to_none(self):
        assert reg.resolve(None) is None
        assert reg.resolve("") is None


class TestModelFacts:
    def test_granite_311m_matches_the_existing_column_width(self):
        """768 is what makes granite a drop-in for an mpnet index."""
        assert reg.GRANITE_311M.dimension == reg.MPNET.dimension == 768

    def test_granite_97m_is_narrower(self):
        assert reg.GRANITE_97M.dimension == 384

    def test_pooling_and_normalisation_are_recorded(self):
        assert reg.MPNET.pooling == "mean"
        assert reg.GRANITE_311M.pooling == "cls"
        assert all(m.normalize for m in reg.MODELS)

    def test_granite_context_is_much_wider_than_mpnet(self):
        assert reg.GRANITE_311M.max_input_tokens == 32768
        assert reg.MPNET.max_input_tokens == 384

    def test_local_runners_carry_a_repo_and_onnx_file(self):
        for model in reg.MODELS:
            if model.provider == "fastembed":
                assert model.repo, f"{model.name} has no repo"
                assert model.onnx_file, f"{model.name} has no onnx_file"

    def test_openai_model_needs_no_local_artifacts(self):
        assert reg.OPENAI_ADA_002.provider == "openai"
        assert reg.OPENAI_ADA_002.repo is None


class TestHelpers:
    def test_dimension_for_known_and_unknown(self):
        assert reg.dimension_for(reg.GRANITE_97M.name) == 384
        assert reg.dimension_for("nope/nope") is None

    def test_max_input_tokens_for_known_and_unknown(self):
        assert reg.max_input_tokens_for("granite-311m") == 32768
        assert reg.max_input_tokens_for("nope/nope") is None

    def test_known_names_lists_canonical_spellings(self):
        names = reg.known_names()
        assert reg.MPNET.name in names
        assert reg.GRANITE_311M.name in names

    def test_defaults_point_at_the_intended_models(self):
        """Existing installs stay on mpnet; new installs get granite."""
        assert reg.DEFAULT_LEGACY == reg.MPNET.name
        assert reg.DEFAULT_NEW_INSTALL == reg.GRANITE_311M.name

    def test_no_alias_collisions_between_models(self):
        seen = {}
        for model in reg.MODELS:
            for key in (model.name, *model.aliases):
                assert key.lower() not in seen, f"{key} claimed twice"
                seen[key.lower()] = model
