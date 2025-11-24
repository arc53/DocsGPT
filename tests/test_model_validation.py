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
    ModelRegistry.get_instance()

    # Test with a model that should exist (docsgpt-local is always added)
    assert validate_model_id("docsgpt-local") is True

    # Test with invalid model_id
    assert validate_model_id("invalid-model-xyz-123") is False

    # Test with None
    assert validate_model_id(None) is False


@pytest.mark.unit
def test_get_base_url_for_model():
    """Test retrieving base_url for a model"""
    # Test with a model that doesn't have base_url
    result = get_base_url_for_model("docsgpt-local")
    assert result is None  # docsgpt-local doesn't have custom base_url

    # Test with invalid model
    result = get_base_url_for_model("invalid-model")
    assert result is None


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
