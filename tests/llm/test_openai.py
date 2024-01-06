import unittest
from application.llm.openai import OpenAILLM

class TestOpenAILLM(unittest.TestCase):

    def setUp(self):
        self.api_key = "test_api_key"
        self.llm = OpenAILLM(self.api_key)

    def test_init(self):
        self.assertEqual(self.llm.api_key, self.api_key)
