from application.llm.base import BaseLLM
from application.core.settings import settings
import json
import io


class LineIterator:
    """
    A helper class for parsing the byte stream input.

    The output of the model will be in the following format:
    ```
    b'{"outputs": [" a"]}\n'
    b'{"outputs": [" challenging"]}\n'
    b'{"outputs": [" problem"]}\n'
    ...
    ```

    While usually each PayloadPart event from the event stream will contain a byte array
    with a full json, this is not guaranteed and some of the json objects may be split across
    PayloadPart events. For example:
    ```
    {'PayloadPart': {'Bytes': b'{"outputs": '}}
    {'PayloadPart': {'Bytes': b'[" problem"]}\n'}}
    ```

    This class accounts for this by concatenating bytes written via the 'write' function
    and then exposing a method which will return lines (ending with a '\n' character) within
    the buffer via the 'scan_lines' function. It maintains the position of the last read
    position to ensure that previous bytes are not exposed again.
    """

    def __init__(self, stream):
        self.byte_iterator = iter(stream)
        self.buffer = io.BytesIO()
        self.read_pos = 0

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            self.buffer.seek(self.read_pos)
            line = self.buffer.readline()
            if line and line[-1] == ord("\n"):
                self.read_pos += len(line)
                return line[:-1]
            try:
                chunk = next(self.byte_iterator)
            except StopIteration:
                if self.read_pos < self.buffer.getbuffer().nbytes:
                    continue
                raise
            if "PayloadPart" not in chunk:
                print("Unknown event type:" + chunk)
                continue
            self.buffer.seek(0, io.SEEK_END)
            self.buffer.write(chunk["PayloadPart"]["Bytes"])


class SagemakerAPILLM(BaseLLM):

    def __init__(self, api_key, *args, **kwargs):
        import boto3

        runtime = boto3.client(
            "runtime.sagemaker",
            aws_access_key_id="xxx",
            aws_secret_access_key="xxx",
            region_name="us-west-2",
        )

        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.endpoint = settings.SAGEMAKER_ENDPOINT
        self.runtime = runtime

    def _raw_gen(self, model, messages, stream=False, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        # Construct payload for endpoint
        payload = {
            "inputs": prompt,
            "stream": False,
            "parameters": {
                "do_sample": True,
                "temperature": 0.1,
                "max_new_tokens": 30,
                "repetition_penalty": 1.03,
                "stop": ["</s>", "###"],
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        # Invoke the endpoint
        response = self.runtime.invoke_endpoint(
            EndpointName=self.endpoint, ContentType="application/json", Body=body_bytes
        )
        result = json.loads(response["Body"].read().decode())
        import sys

        print(result[0]["generated_text"], file=sys.stderr)
        return result[0]["generated_text"][len(prompt) :]

    def _raw_gen_stream(self, model, messages, stream=True, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        # Construct payload for endpoint
        payload = {
            "inputs": prompt,
            "stream": True,
            "parameters": {
                "do_sample": True,
                "temperature": 0.1,
                "max_new_tokens": 512,
                "repetition_penalty": 1.03,
                "stop": ["</s>", "###"],
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")

        # Invoke the endpoint
        response = self.runtime.invoke_endpoint_with_response_stream(
            EndpointName=self.endpoint, ContentType="application/json", Body=body_bytes
        )
        # result = json.loads(response['Body'].read().decode())
        event_stream = response["Body"]
        start_json = b"{"
        for line in LineIterator(event_stream):
            if line != b"" and start_json in line:
                # print(line)
                data = json.loads(line[line.find(start_json) :].decode("utf-8"))
                if data["token"]["text"] not in ["</s>", "###"]:
                    print(data["token"]["text"], end="")
                    yield data["token"]["text"]
