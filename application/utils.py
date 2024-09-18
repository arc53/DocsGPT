import tiktoken

_encoding = None

def get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding

def num_tokens_from_string(string: str) -> int:
    encoding = get_encoding()
    num_tokens = len(encoding.encode(string))
    return num_tokens

def count_tokens_docs(docs):
    docs_content = ""
    for doc in docs:
        docs_content += doc.page_content

    tokens = num_tokens_from_string(docs_content)
    return tokens