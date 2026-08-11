"""
Tests for model validation and base_url functionality
"""
import pytest
from application.core.model_settings import (
    AvailableModel,
    ModelCapabilities,
    ModelProvider,
    ModelRegistry,
)
from application.core.model_utils import (
    get_base_url_for_model,
    validate_model_id,
)


@pytest.mark.unit
def test_model_with_base_url():
    """Test that AvailableModel can store and retrieve base_url"""
    model = AvailableModel(
        id="test-model",
        provider=ModelProvider.OPENAI,
        display_name="Test Model",
        description="Test model with custom base URL",
        base_url="https://custom-endpoint.com/v1",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=8192,
        ),
    )

    assert model.base_url == "https://custom-endpoint.com/v1"
    assert model.id == "test-model"
    assert model.provider == ModelProvider.OPENAI

    # Test to_dict includes base_url
    model_dict = model.to_dict()
    assert "base_url" in model_dict
    assert model_dict["base_url"] == "https://custom-endpoint.com/v1"


@pytest.mark.unit
def test_model_without_base_url():
    """Test that models without base_url still work"""
    model = AvailableModel(
        id="test-model-no-url",
        provider=ModelProvider.OPENAI,
        display_name="Test Model",
        description="Test model without base URL",
        capabilities=ModelCapabilities(
            supports_tools=True,
            context_window=8192,
        ),
    )

    assert model.base_url is None

    # Test to_dict doesn't include base_url when None
    model_dict = model.to_dict()
    assert "base_url" not in model_dict


@pytest.mark.unit
def test_validate_model_id():
    """Test model_id validation"""
    # Get the registry instance to check what models are available
    registry = ModelRegistry.get_instance()

    # Test with a model that exists in the registry
    available_models = registry.get_all_models()
    if available_models:
        assert validate_model_id(available_models[0].id) is True

    # Test with invalid model_id
    assert validate_model_id("invalid-model-xyz-123") is False

    # Test with None
    assert validate_model_id(None) is False


@pytest.mark.unit
def test_get_base_url_for_model():
    """Test retrieving base_url for a model"""
    # Test with invalid model
    result = get_base_url_for_model("invalid-model")
    assert result is None

    # Test with a model that exists but may or may not have base_url
    registry = ModelRegistry.get_instance()
    available_models = registry.get_all_models()
    if available_models:
        model = available_models[0]
        result = get_base_url_for_model(model.id)
        # Result should match the model's base_url (could be None or a string)
        assert result == model.base_url


@pytest.mark.unit
def test_model_validation_error_message():
    """Test that validation provides helpful error messages"""
    from application.api.answer.services.stream_processor import StreamProcessor

    # Create processor with invalid model_id
    data = {"model_id": "invalid-model-xyz"}
    processor = StreamProcessor(data, None)

    # Should raise ValueError with helpful message
    with pytest.raises(ValueError) as exc_info:
        processor._validate_and_set_model()

    error_msg = str(exc_info.value)
    assert "Invalid model_id 'invalid-model-xyz'" in error_msg
    assert "Available models:" in error_msg


@pytest.mark.unit
def test_capabilities_reasoning_effort_defaults_none():
    """reasoning_effort is an optional capability, None by default."""
    assert ModelCapabilities().reasoning_effort is None


@pytest.mark.unit
def test_yaml_reasoning_effort_and_upstream_model_id(tmp_path):
    """Two distinct ids can share one upstream model, each with its own effort."""
    from application.core.model_yaml import load_model_yamls

    (tmp_path / "openai.yaml").write_text(
        "provider: openai\n"
        "models:\n"
        "  - id: mini-low\n"
        "    upstream_model_id: mini\n"
        "    reasoning_effort: low\n"
        "  - id: mini-high\n"
        "    upstream_model_id: mini\n"
        "    reasoning_effort: high\n"
        "  - id: plain\n",
        encoding="utf-8",
    )

    catalogs = load_model_yamls([tmp_path])
    models = {m.id: m for c in catalogs for m in c.models}

    assert models["mini-low"].upstream_model_id == "mini"
    assert models["mini-low"].capabilities.reasoning_effort == "low"
    assert models["mini-high"].upstream_model_id == "mini"
    assert models["mini-high"].capabilities.reasoning_effort == "high"

    # No upstream_model_id / reasoning_effort given → fall back to id / None.
    assert models["plain"].upstream_model_id is None
    assert models["plain"].capabilities.reasoning_effort is None


@pytest.mark.unit
def test_yaml_invalid_reasoning_effort_rejected(tmp_path):
    """A bad reasoning_effort value aborts the YAML load."""
    from application.core.model_yaml import ModelYAMLError, load_model_yamls

    (tmp_path / "openai.yaml").write_text(
        "provider: openai\n"
        "models:\n"
        "  - id: bad\n"
        "    reasoning_effort: turbo\n",
        encoding="utf-8",
    )

    with pytest.raises(ModelYAMLError):
        load_model_yamls([tmp_path])


@pytest.mark.unit
def test_yaml_reasoning_effort_accepts_full_enum(tmp_path):
    """Every value OpenAI documents across the GPT-5 series must parse."""
    from application.core.model_yaml import (
        VALID_REASONING_EFFORTS,
        load_model_yamls,
    )

    assert VALID_REASONING_EFFORTS == {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }

    lines = ["provider: openai", "models:"]
    for effort in sorted(VALID_REASONING_EFFORTS):
        lines.append(f"  - id: m-{effort}")
        lines.append(f"    reasoning_effort: {effort}")
    (tmp_path / "openai.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    catalogs = load_model_yamls([tmp_path])
    parsed = {m.id: m.capabilities.reasoning_effort for c in catalogs for m in c.models}
    for effort in VALID_REASONING_EFFORTS:
        assert parsed[f"m-{effort}"] == effort


@pytest.mark.unit
def test_openai_apply_reasoning_effort():
    """OpenAILLM injects reasoning_effort from capabilities; caller wins."""
    from application.llm.openai import OpenAILLM

    llm = OpenAILLM.__new__(OpenAILLM)

    # Pulled from capabilities when the caller didn't set one.
    llm.capabilities = ModelCapabilities(reasoning_effort="high")
    kwargs: dict = {}
    llm._apply_reasoning_effort(kwargs)
    assert kwargs["reasoning_effort"] == "high"

    # A caller-supplied value is never overridden.
    kwargs = {"reasoning_effort": "low"}
    llm._apply_reasoning_effort(kwargs)
    assert kwargs["reasoning_effort"] == "low"

    # No capabilities / no configured effort → key is not added.
    llm.capabilities = None
    kwargs = {}
    llm._apply_reasoning_effort(kwargs)
    assert "reasoning_effort" not in kwargs

    llm.capabilities = ModelCapabilities()
    kwargs = {}
    llm._apply_reasoning_effort(kwargs)
    assert "reasoning_effort" not in kwargs
