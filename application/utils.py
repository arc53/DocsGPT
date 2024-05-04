from transformers import GPT2TokenizerFast

tokenizer = GPT2TokenizerFast.from_pretrained('gpt2')
def count_tokens(string):
    
    return len(tokenizer(string)['input_ids'])