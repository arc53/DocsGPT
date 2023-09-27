# FILEPATH: /Users/alextu/Documents/GitHub/DocsGPT/tests/llm/test_openai.py

import unittest
from unittest.mock import patch, Mock
from application.llm.openai import OpenAILLM, AzureOpenAILLM

class TestOpenAILLM(unittest.TestCase):

    def setUp(self):
        self.api_key = "test_api_key"
        self.llm = OpenAILLM(self.api_key)

    def test_init(self):
        self.assertEqual(self.llm.api_key, self.api_key)

    @patch('application.llm.openai.openai.ChatCompletion.create')
    def test_gen(self, mock_create):
        model = "test_model"
        engine = "test_engine"
        messages = ["test_message"]
        response = {"choices": [{"message": {"content": "test_response"}}]}
        mock_create.return_value = response
        result = self.llm.gen(model, engine, messages)
        self.assertEqual(result, "test_response")

    @patch('application.llm.openai.openai.ChatCompletion.create')
    def test_gen_stream(self, mock_create):
        model = "test_model"
        engine = "test_engine"
        messages = ["test_message"]
        response = [{"choices": [{"delta": {"content": "test_response"}}]}]
        mock_create.return_value = response
        result = list(self.llm.gen_stream(model, engine, messages))
        self.assertEqual(result, ["test_response"])
