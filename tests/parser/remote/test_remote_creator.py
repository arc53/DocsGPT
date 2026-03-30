"""Tests for application.parser.remote.remote_creator covering lines 31-34."""

import pytest
from unittest.mock import MagicMock


@pytest.mark.unit
class TestRemoteCreator:
    def test_create_loader_valid_type(self):
        """Cover line 34: returns loader instance for valid type."""
        from application.parser.remote.remote_creator import RemoteCreator

        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["url"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("url")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders

    def test_create_loader_invalid_type_raises(self):
        """Cover lines 32-33: raises ValueError for unknown type."""
        from application.parser.remote.remote_creator import RemoteCreator

        with pytest.raises(ValueError, match="No loader class found"):
            RemoteCreator.create_loader("nonexistent_xyz")

    def test_create_loader_case_insensitive(self):
        """Cover line 31: type.lower() normalization."""
        from application.parser.remote.remote_creator import RemoteCreator

        mock_loader_cls = MagicMock()
        original_loaders = RemoteCreator.loaders.copy()
        RemoteCreator.loaders["sitemap"] = mock_loader_cls
        try:
            RemoteCreator.create_loader("SITEMAP")
            mock_loader_cls.assert_called_once()
        finally:
            RemoteCreator.loaders = original_loaders
