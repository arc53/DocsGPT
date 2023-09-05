from application.app import get_vectorstore, llm_call
import os


# Test cases for get_vectorstore function
def test_no_active_docs():
    data = {}
    assert get_vectorstore(data) == os.path.join("application", "")


def test_local_default_active_docs():
    data = {"active_docs": "local/default"}
    assert get_vectorstore(data) == os.path.join("application", "")


def test_local_non_default_active_docs():
    data = {"active_docs": "local/something"}
    assert get_vectorstore(data) == os.path.join("application", "indexes/local/something")


def test_default_active_docs():
    data = {"active_docs": "default"}
    assert get_vectorstore(data) == os.path.join("application", "")


def test_complex_active_docs():
    data = {"active_docs": "local/other/path"}
    assert get_vectorstore(data) == os.path.join("application", "indexes/local/other/path")

def test_llm_call():
    messages = [{"role": "user", "content": "Hey, how's it going?"}]
    response = llm_call(model="gpt-3.5-turbo", messages=messages, stream=True, max_tokens=256, temperature=0)
    complete_response = ""
    for chunk in response:
        print(chunk["choices"][0]["delta"])
        complete_response += chunk["choices"][0]["delta"]["content"]
    if complete_response == "": 
        raise Exception("Empty response received")
    assert len(complete_response) > 0

test_llm_call()