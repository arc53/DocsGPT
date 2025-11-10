from anthropic import AI_PROMPT, Anthropic, HUMAN_PROMPT

from application.core.settings import settings
from application.llm.base import BaseLLM


class AnthropicLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):

        super().__init__(*args, **kwargs)
        self.api_key = api_key or settings.ANTHROPIC_API_KEY or settings.API_KEY
        self.user_api_key = user_api_key
        self.anthropic = Anthropic(api_key=self.api_key)
        self.HUMAN_PROMPT = HUMAN_PROMPT
        self.AI_PROMPT = AI_PROMPT

    def _raw_gen(
        self,
        baseself,
        model,
        messages,
        stream=False,
        tools=None,
        max_tokens=300,
        **kwargs,
    ):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Context \n {context} \n ### Question \n {user_question}"
        if stream:
            return self.gen_stream(model, prompt, stream, max_tokens, **kwargs)
        completion = self.anthropic.completions.create(
            model=model,
            max_tokens_to_sample=max_tokens,
            stream=stream,
            prompt=f"{self.HUMAN_PROMPT} {prompt}{self.AI_PROMPT}",
        )
        return completion.completion

    def _raw_gen_stream(
        self,
        baseself,
        model,
        messages,
        stream=True,
        tools=None,
        max_tokens=300,
        **kwargs,
    ):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Context \n {context} \n ### Question \n {user_question}"
        stream_response = self.anthropic.completions.create(
            model=model,
            prompt=f"{self.HUMAN_PROMPT} {prompt}{self.AI_PROMPT}",
            max_tokens_to_sample=max_tokens,
            stream=True,
        )

        try:
            for completion in stream_response:
                yield completion.completion
        finally:
            if hasattr(stream_response, "close"):
                stream_response.close()
