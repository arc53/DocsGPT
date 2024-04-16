from application.llm.base import BaseLLM
from application.core.settings import settings


class AnthropicLLM(BaseLLM):

    def __init__(self, api_key=None, user_api_key=None, *args, **kwargs):
        from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT

        super().__init__(*args, **kwargs)
        self.api_key = (
            api_key or settings.ANTHROPIC_API_KEY
        )  # If not provided, use a default from settings
        self.user_api_key = user_api_key
        self.anthropic = Anthropic(api_key=self.api_key)
        self.HUMAN_PROMPT = HUMAN_PROMPT
        self.AI_PROMPT = AI_PROMPT

    def _raw_gen(
        self, baseself, model, messages, stream=False, max_tokens=300, **kwargs
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
        self, baseself, model, messages, stream=True, max_tokens=300, **kwargs
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

        for completion in stream_response:
            yield completion.completion
