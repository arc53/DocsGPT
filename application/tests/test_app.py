from application.app import get_vectorstore


# Test cases for get_vectorstore function
def test_no_active_docs():
    data = {}
    assert get_vectorstore(data) == ""


def test_default_active_docs():
    data = {"active_docs": "default"}
    assert get_vectorstore(data) == ""


def test_local_default_active_docs():
    data = {"active_docs": "local/default"}
    assert get_vectorstore(data) == ""


def test_local_custom_active_docs():
    data = {"active_docs": "local/custom_index"}
    assert get_vectorstore(data) == "indexes/local/custom_index"


def test_remote_active_docs():
    data = {"active_docs": "remote_index"}
    assert get_vectorstore(data) == "vectors/remote_index"


def test_active_docs_not_in_data():
    data = {"other_key": "value"}
    assert get_vectorstore(data) == ""


def test_multiple_slashes_in_active_docs():
    data = {"active_docs": "local/some/other/index"}
    assert get_vectorstore(data) == "indexes/local/some/other/index"
