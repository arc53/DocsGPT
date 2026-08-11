"""Tests for the graphrag_available() pgvector-gated flag (D29)."""

from __future__ import annotations

import pytest

from application.graphrag import graphrag_available
from application.core.settings import settings


@pytest.mark.unit
class TestGraphragAvailable:
    def test_true_only_when_enabled_and_pgvector(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        assert graphrag_available() is True

    def test_false_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False)
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        assert graphrag_available() is False

    def test_false_when_store_not_pgvector(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", True)
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        assert graphrag_available() is False

    def test_false_when_disabled_and_not_pgvector(self, monkeypatch):
        monkeypatch.setattr(settings, "GRAPHRAG_ENABLED", False)
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        assert graphrag_available() is False
