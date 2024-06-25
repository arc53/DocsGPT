from application.llm.base import BaseLLM
from application.core.settings import settings

class LlamaSingleton:
    _instances = {}

    @classmethod
    def get_instance(cls, llm_name):
        if llm_name not in cls._instances:
            try:
                from llama_cpp import Llama
            except ImportError:
                raise ImportError(
                    "Please install llama_cpp using pip install llama-cpp-python"
                )
            cls._instances[llm_name] = Llama(model_path=llm_name, n_ctx=2048)
        return cls._instances[llm_name]

class LlamaCpp(BaseLLM):
    def __init__(
        self,
        api_key=None,
        user_api_key=None,
        llm_name=settings.MODEL_PATH,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.api_key = api_key
        self.user_api_key = user_api_key
        self.llama = LlamaSingleton.get_instance(llm_name)

    def _raw_gen(self, baseself, model, messages, stream=False, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"
        result = self.llama(prompt, max_tokens=150, echo=False)
        return result["choices"][0]["text"].split("### Answer \n")[-1]

    def _raw_gen_stream(self, baseself, model, messages, stream=True, **kwargs):
        context = messages[0]["content"]
        user_question = messages[-1]["content"]
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"
        result = self.llama(prompt, max_tokens=150, echo=False, stream=stream)
        for item in result:
            for choice in item["choices"]:
                yield choice["text"]