import socket

import pytest


@pytest.fixture(autouse=True)
def default_port_is_available(monkeypatch):
    from docsgpt.deploy import commands, stack

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        test_port = probe.getsockname()[1]

    port_is_free = commands._port_is_free

    def isolated_port_is_free(port):
        if port == stack.DEFAULT_PORT:
            port = test_port
        return port_is_free(port)

    monkeypatch.setattr(
        commands,
        "_port_is_free",
        isolated_port_is_free,
    )
