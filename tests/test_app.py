from application.app import get_vectorstore, is_azure_configured
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


def test_is_azure_configured():
    assert not is_azure_configured()
