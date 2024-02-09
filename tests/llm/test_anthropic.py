import unittest
from unittest.mock import patch, Mock
from application.llm.anthropic import AnthropicLLM

class TestAnthropicLLM(unittest.TestCase):

    def setUp(self):
        self.api_key = "TEST_API_KEY"
        self.llm = AnthropicLLM(api_key=self.api_key)

    @patch("application.llm.anthropic.settings")
    def test_init_default_api_key(self, mock_settings):
        mock_settings.ANTHROPIC_API_KEY = "DEFAULT_API_KEY"
        llm = AnthropicLLM()
        self.assertEqual(llm.api_key, "DEFAULT_API_KEY")

    def test_gen(self):
        messages = [
            {"content": "context"},
            {"content": "question"}
        ]
        mock_response = Mock()
        mock_response.completion = "test completion"

        with patch.object(self.llm.anthropic.completions, "create", return_value=mock_response) as mock_create:
            response = self.llm.gen("test_model", messages)
            self.assertEqual(response, "test completion")

            prompt_expected = "### Context \n context \n ### Question \n question"
            mock_create.assert_called_with(
                model="test_model",
                max_tokens_to_sample=300,
                stream=False,
                prompt=f"{self.llm.HUMAN_PROMPT} {prompt_expected}{self.llm.AI_PROMPT}"
            )

    def test_gen_stream(self):
        messages = [
            {"content": "context"},
            {"content": "question"}
        ]
        mock_responses = [Mock(completion="response_1"), Mock(completion="response_2")]

        with patch.object(self.llm.anthropic.completions, "create", return_value=iter(mock_responses)) as mock_create:
            responses = list(self.llm.gen_stream("test_model", messages))
            self.assertListEqual(responses, ["response_1", "response_2"])

            prompt_expected = "### Context \n context \n ### Question \n question"
            mock_create.assert_called_with(
                model="test_model",
                prompt=f"{self.llm.HUMAN_PROMPT} {prompt_expected}{self.llm.AI_PROMPT}",
                max_tokens_to_sample=300,
                stream=True
            )

if __name__ == "__main__":
    unittest.main()
