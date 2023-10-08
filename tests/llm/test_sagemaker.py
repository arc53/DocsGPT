# FILEPATH: /path/to/test_sagemaker.py

import json
import unittest
from unittest.mock import MagicMock, patch
from application.llm.sagemaker import SagemakerAPILLM, LineIterator

class TestSagemakerAPILLM(unittest.TestCase):
    
    def setUp(self):
        self.sagemaker = SagemakerAPILLM()
        self.context = "This is the context"
        self.user_question = "What is the answer?"
        self.messages = [
            {"content": self.context},
            {"content": "Some other message"},
            {"content": self.user_question}
        ]
        self.prompt = f"### Instruction \n {self.user_question} \n ### Context \n {self.context} \n ### Answer \n"
        self.payload = {
            "inputs": self.prompt,
            "stream": False,
            "parameters": {
                "do_sample": True,
                "temperature": 0.1,
                "max_new_tokens": 30,
                "repetition_penalty": 1.03,
                "stop": ["</s>", "###"]
            }
        }
        self.payload_stream = {
            "inputs": self.prompt,
            "stream": True,
            "parameters": {
                "do_sample": True,
                "temperature": 0.1,
                "max_new_tokens": 512,
                "repetition_penalty": 1.03,
                "stop": ["</s>", "###"]
            }
        }
        self.body_bytes = json.dumps(self.payload).encode('utf-8')
        self.body_bytes_stream = json.dumps(self.payload_stream).encode('utf-8')
        self.response = {
            "Body": MagicMock()
        }
        self.result = [
            {
                "generated_text": "This is the generated text"
            }
        ]
        self.response['Body'].read.return_value.decode.return_value = json.dumps(self.result)
        
    def test_gen(self):
        with patch.object(self.sagemaker.runtime, 'invoke_endpoint', 
                          return_value=self.response) as mock_invoke_endpoint:
            output = self.sagemaker.gen(None, None, self.messages)
            mock_invoke_endpoint.assert_called_once_with(
                EndpointName=self.sagemaker.endpoint,
                ContentType='application/json',
                Body=self.body_bytes
            )
            self.assertEqual(output, 
                             self.result[0]['generated_text'][len(self.prompt):])
    
    def test_gen_stream(self):
        with patch.object(self.sagemaker.runtime, 'invoke_endpoint_with_response_stream', 
                          return_value=self.response) as mock_invoke_endpoint:
            output = list(self.sagemaker.gen_stream(None, None, self.messages))
            mock_invoke_endpoint.assert_called_once_with(
                EndpointName=self.sagemaker.endpoint,
                ContentType='application/json',
                Body=self.body_bytes_stream
            )
            self.assertEqual(output, [])
            
class TestLineIterator(unittest.TestCase):
    
    def setUp(self):
        self.stream = [
            {'PayloadPart': {'Bytes': b'{"outputs": [" a"]}\n'}},
            {'PayloadPart': {'Bytes': b'{"outputs": [" challenging"]}\n'}},
            {'PayloadPart': {'Bytes': b'{"outputs": [" problem"]}\n'}}
        ]
        self.line_iterator = LineIterator(self.stream)
        
    def test_iter(self):
        self.assertEqual(iter(self.line_iterator), self.line_iterator)
        
    def test_next(self):
        self.assertEqual(next(self.line_iterator), b'{"outputs": [" a"]}')
        self.assertEqual(next(self.line_iterator), b'{"outputs": [" challenging"]}')
        self.assertEqual(next(self.line_iterator), b'{"outputs": [" problem"]}')
        
if __name__ == '__main__':
    unittest.main()