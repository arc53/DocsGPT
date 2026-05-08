"""Tests for connector base classes."""


import pytest

from application.parser.connectors.base import BaseConnectorAuth, BaseConnectorLoader
from application.parser.schema.base import Document


class ConcreteAuth(BaseConnectorAuth):
    """Minimal concrete implementation for testing the ABC."""

    def get_authorization_url(self, state=None):
        return f"https://example.com/auth?state={state}"

    def exchange_code_for_tokens(self, authorization_code):
        return {"access_token": "tok", "code": authorization_code}

    def refresh_access_token(self, refresh_token):
        return {"access_token": "new_tok", "refresh_token": refresh_token}

    def is_token_expired(self, token_info):
        return token_info.get("expired", False)


class ConcreteLoader(BaseConnectorLoader):
    """Minimal concrete implementation for testing the ABC."""

    def __init__(self, session_token):
        self.session_token = session_token

    def load_data(self, inputs):
        return [Document(text="test", doc_id="1", extra_info={})]

    def download_to_directory(self, local_dir, source_config=None):
        return {"files_downloaded": 0, "directory_path": local_dir}


class TestBaseConnectorAuth:

    @pytest.mark.unit
    def test_sanitize_token_info_extracts_standard_fields(self):
        auth = ConcreteAuth()
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://token.uri",
            "expiry": 12345,
            "extra_field": "should_not_appear",
        }
        result = auth.sanitize_token_info(token_info)
        assert result == {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://token.uri",
            "expiry": 12345,
        }

    @pytest.mark.unit
    def test_sanitize_token_info_with_extra_kwargs(self):
        auth = ConcreteAuth()
        token_info = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_uri": "https://token.uri",
            "expiry": 100,
        }
        result = auth.sanitize_token_info(token_info, custom_field="custom_val")
        assert result["custom_field"] == "custom_val"
        assert result["access_token"] == "at"

    @pytest.mark.unit
    def test_sanitize_token_info_missing_fields_returns_none(self):
        auth = ConcreteAuth()
        result = auth.sanitize_token_info({})
        assert result["access_token"] is None
        assert result["refresh_token"] is None
        assert result["token_uri"] is None
        assert result["expiry"] is None

    @pytest.mark.unit
    def test_abstract_methods_invocable_on_concrete(self):
        auth = ConcreteAuth()
        assert "example.com" in auth.get_authorization_url("s1")
        assert auth.exchange_code_for_tokens("code1")["access_token"] == "tok"
        assert auth.refresh_access_token("rt")["access_token"] == "new_tok"
        assert auth.is_token_expired({"expired": True}) is True
        assert auth.is_token_expired({"expired": False}) is False


class TestBaseConnectorLoader:

    @pytest.mark.unit
    def test_concrete_loader_init(self):
        loader = ConcreteLoader("session123")
        assert loader.session_token == "session123"

    @pytest.mark.unit
    def test_concrete_loader_load_data(self):
        loader = ConcreteLoader("s")
        docs = loader.load_data({})
        assert len(docs) == 1
        assert docs[0].text == "test"

    @pytest.mark.unit
    def test_concrete_loader_download_to_directory(self):
        loader = ConcreteLoader("s")
        result = loader.download_to_directory("/tmp/test")
        assert result["directory_path"] == "/tmp/test"
        assert result["files_downloaded"] == 0
