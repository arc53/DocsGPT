from application.llm.base import BaseLLM

class OpenAILLM(BaseLLM):

    def __init__(self, api_key):
        global openai
        import openai
        openai.api_key = api_key
        self.api_key = api_key  # Save the API key to be used later

    def _get_openai(self):
        # Import openai when needed
        import openai
        # Set the API key every time you import openai
        openai.api_key = self.api_key
        return openai

    def gen(self, *args, **kwargs):
        # This is just a stub. In the real implementation, you'd hit the OpenAI API or any other service.
        return "Non-streaming response from OpenAI."

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):
        # openai = self._get_openai()  # Get the openai module with the API key set
        response = openai.ChatCompletion.create(
            model=model,
            engine=engine,
            messages=messages,
            stream=stream,
            **kwargs
        )

        for line in response:
            if "content" in line["choices"][0]["delta"]:
                yield line["choices"][0]["delta"]["content"]
