from application.llm.base import BaseLLM

class HuggingFaceLLM(BaseLLM):

    def __init__(self, api_key, llm_name='Arc53/DocsGPT-7B'):
        global hf

        from langchain.llms import HuggingFacePipeline
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        tokenizer = AutoTokenizer.from_pretrained(llm_name)
        model = AutoModelForCausalLM.from_pretrained(llm_name)
        pipe = pipeline(
            "text-generation", model=model,
            tokenizer=tokenizer, max_new_tokens=2000,
            device_map="auto", eos_token_id=tokenizer.eos_token_id
        )
        hf = HuggingFacePipeline(pipeline=pipe)

    def gen(self, model, engine, messages, stream=False, **kwargs):
        context = messages[0]['content']
        user_question = messages[-1]['content']
        prompt = f"### Instruction \n {user_question} \n ### Context \n {context} \n ### Answer \n"

        result = hf(prompt)

        return result.content

    def gen_stream(self, model, engine, messages, stream=True, **kwargs):

        raise NotImplementedError("HuggingFaceLLM Streaming is not implemented yet.")

