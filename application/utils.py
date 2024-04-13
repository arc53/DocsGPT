from transformers import GPT2TokenizerFast


def count_tokens(string):
    tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
    return len(tokenizer(string)['input_ids'])