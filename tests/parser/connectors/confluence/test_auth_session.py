"""Tests for Confluence auth get_token_info_from_session using pg_conn."""

from contextlib import contextmanager
from unittest.mock import patch



@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "docsgpt.storage.db.session.db_readonly", _yield
    ):
        yield


