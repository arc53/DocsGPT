"""Stand-in for the connection service in connector loader tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import patch


@contextmanager
def patch_tokens(token_info: dict, connection_id: str = "conn-1"):
    """Make every loader resolve ``connection_id`` and read ``token_info``.

    Yields the ``get_valid_token_info`` mock so a test can assert on or
    change what a refresh returns.
    """
    with ExitStack() as stack:
        stack.enter_context(
            patch("docsgpt.connectors.service.connection_id_for_session_token", return_value=connection_id)
        )
        tokens = stack.enter_context(
            patch("docsgpt.connectors.service.get_valid_token_info", return_value=token_info)
        )
        yield tokens
