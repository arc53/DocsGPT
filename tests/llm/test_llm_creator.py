"""Unit tests for application/llm/llm_creator.py — LLMCreator provider routing.

These tests exercise the pure routing logic of LLMCreator.create_llm() with no
external dependencies (no vector stores, no DB, no API calls). They follow the
conventions from tests/conftest.py and tests/llm/test_base_llm.py.
"""

from application.llm.llm_creator import LLMCreator


@pytest.mark.unit
class TestLLMCreatorRouting:
    """Verify that each known provider name routes to the correct llm_class."""

    @pytest.mark.parametrize(
        "provider_name, expected_class_name",
        [
            ("openai", "OpenAILLM"),
            ("anthropic", "AnthropicLLM"),
            ("groq", "GroqLLM"),
            ("openrouter", "OpenRouterLLM"),
            ("novita", "NovitaLLM"),
            ("llama_cpp", "LlamaCppLLM"),
        ],
    )
    def test_known_provider_routes_correctly(self, provider_name, expected_class_name):
        # Use model_id=None so the BYOM resolution block (lines 55-126 of
        # llm_creator.py) is skipped; we test only the provider→class mapping.
        llm = LLMCreator.create_llm(
            provider_name,
            api_key="sk-test-key123",
            user_api_key=None,
            decoded_token={"sub": "test_user"},
            model_id=None,
        )
        assert type(llm).__name__ == expected_class_name


@pytest.mark.unit
class TestLLMCreatorUnknownProvider:
    """Verify that an unrecognised provider string raises ValueError."""

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="No LLM class found for type"):
            LLMCreator.create_llm(
                "fake_provider",
                api_key="sk-key",
                user_api_key=None,
                decoded_token={"sub": "u"},
            )


@pytest.mark.unit
class TestLLMCreatorHuggingFaceRaises:
    """Verify that HuggingFace (catalogued but llm_class=None) also raises."""

    def test_huggingface_provider_raises(self):
        with pytest.raises(ValueError, match="No LLM class found for type"):
            LLMCreator.create_llm(
                "huggingface",
                api_key="sk-key",
                user_api_key=None,
                decoded_token={"sub": "u"},
            )