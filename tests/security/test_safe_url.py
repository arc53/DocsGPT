"""Unit tests for ``application.security.safe_url``.

These tests must run offline, so every "valid public host" case mocks
``socket.getaddrinfo`` to return a known public IP. Cases that test
IP-literal validation do not need DNS at all and rely on the
short-circuit path inside ``validate_user_base_url``.
"""

from __future__ import annotations

import socket
from unittest import mock

import pytest
import requests

from application.security.safe_url import (
    UnsafeUserUrlError,
    _PinnedHTTPSTransport,
    pinned_httpx_client,
    pinned_post,
    validate_user_base_url,
)


def _addrinfo(*ips: str) -> list[tuple]:
    """Build a fake ``socket.getaddrinfo`` return value for ``ips``."""

    out: list[tuple] = []
    for ip in ips:
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        port_tuple = (ip, 0, 0, 0) if family == socket.AF_INET6 else (ip, 0)
        out.append((family, socket.SOCK_STREAM, 0, "", port_tuple))
    return out


# Valid URLs (DNS mocked to a known-public IP)


@pytest.mark.unit
def test_allows_openai_api():
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")):
        assert validate_user_base_url("https://api.openai.com/v1") is None


@pytest.mark.unit
def test_allows_mistral_api():
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("172.67.144.116")):
        assert validate_user_base_url("https://api.mistral.ai/v1") is None


@pytest.mark.unit
def test_allows_http_with_port():
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        assert validate_user_base_url("http://example.com:8080/v1") is None


# Scheme rejection


@pytest.mark.unit
def test_rejects_file_scheme():
    with pytest.raises(UnsafeUserUrlError, match="scheme"):
        validate_user_base_url("file:///etc/passwd")


@pytest.mark.unit
def test_rejects_gopher_scheme():
    with pytest.raises(UnsafeUserUrlError, match="scheme"):
        validate_user_base_url("gopher://example.com")


@pytest.mark.unit
def test_rejects_ftp_scheme():
    with pytest.raises(UnsafeUserUrlError, match="scheme"):
        validate_user_base_url("ftp://example.com")


# Hostname-string blocklist


@pytest.mark.unit
def test_rejects_localhost_hostname():
    with pytest.raises(UnsafeUserUrlError, match="not allowed"):
        validate_user_base_url("https://localhost/v1")


@pytest.mark.unit
def test_rejects_localhost_localdomain():
    with pytest.raises(UnsafeUserUrlError, match="not allowed"):
        validate_user_base_url("https://localhost.localdomain/v1")


@pytest.mark.unit
def test_rejects_localhost_uppercase():
    # Hostname check must be case-insensitive.
    with pytest.raises(UnsafeUserUrlError, match="not allowed"):
        validate_user_base_url("https://LocalHost/v1")


@pytest.mark.unit
def test_rejects_ip6_localhost_alias():
    with pytest.raises(UnsafeUserUrlError, match="not allowed"):
        validate_user_base_url("https://ip6-localhost/v1")


@pytest.mark.unit
def test_rejects_gcp_metadata_hostname():
    with pytest.raises(UnsafeUserUrlError, match="not allowed"):
        validate_user_base_url("https://metadata.google.internal/computeMetadata/v1/")


# IP-literal rejection (no DNS hit needed; covered by short-circuit)


@pytest.mark.unit
def test_rejects_loopback_ipv4_literal():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://127.0.0.1/v1")


@pytest.mark.unit
def test_rejects_loopback_ipv6_literal():
    with pytest.raises(UnsafeUserUrlError, match="not allowed|blocked"):
        validate_user_base_url("https://[::1]/v1")


@pytest.mark.unit
def test_rejects_private_10_8():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://10.0.0.5/v1")


@pytest.mark.unit
def test_rejects_private_172_16_low_boundary():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://172.16.0.5/v1")


@pytest.mark.unit
def test_rejects_private_172_16_high_boundary():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://172.31.0.5/v1")


@pytest.mark.unit
def test_rejects_private_192_168():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://192.168.1.1/v1")


@pytest.mark.unit
def test_rejects_aws_metadata_link_local():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://169.254.169.254/latest/meta-data/")


@pytest.mark.unit
def test_rejects_unique_local_ipv6():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://[fc00::1]/v1")


@pytest.mark.unit
def test_rejects_link_local_ipv6():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://[fe80::1]/v1")


@pytest.mark.unit
def test_rejects_multicast_ipv4():
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://224.0.0.1/v1")


@pytest.mark.unit
def test_rejects_unspecified_zero_address():
    # 0.0.0.0 is in the literal hostname blocklist AND also caught as
    # unspecified; either error message is acceptable.
    with pytest.raises(UnsafeUserUrlError, match="not allowed|blocked"):
        validate_user_base_url("https://0.0.0.0/v1")


@pytest.mark.unit
def test_rejects_carrier_grade_nat():
    # 100.64.0.0/10 is NOT covered by ``ipaddress.is_private``.
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        validate_user_base_url("https://100.64.0.1/v1")


# Parse / structural failures


@pytest.mark.unit
def test_rejects_garbage_string():
    with pytest.raises(UnsafeUserUrlError):
        validate_user_base_url("not a url")


@pytest.mark.unit
def test_rejects_empty_string():
    with pytest.raises(UnsafeUserUrlError, match="non-empty"):
        validate_user_base_url("")


@pytest.mark.unit
def test_rejects_whitespace_only_string():
    with pytest.raises(UnsafeUserUrlError, match="non-empty"):
        validate_user_base_url("   ")


@pytest.mark.unit
def test_rejects_url_without_hostname():
    with pytest.raises(UnsafeUserUrlError):
        validate_user_base_url("https:///v1")


# DNS-mocking tests for hostnames (rebinding-style scenarios)


@pytest.mark.unit
def test_rejects_hostname_resolving_only_to_private():
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
        with pytest.raises(UnsafeUserUrlError, match="blocked address"):
            validate_user_base_url("https://internal.example.com/v1")


@pytest.mark.unit
def test_rejects_hostname_with_mixed_public_and_private():
    # Public IP first, private second — must still reject because ANY
    # blocked address in the answer set is enough.
    with mock.patch(
        "socket.getaddrinfo",
        return_value=_addrinfo("93.184.216.34", "10.0.0.5"),
    ):
        with pytest.raises(UnsafeUserUrlError, match="blocked address"):
            validate_user_base_url("https://rebinding.example.com/v1")


@pytest.mark.unit
def test_rejects_hostname_when_dns_fails():
    with mock.patch(
        "socket.getaddrinfo",
        side_effect=socket.gaierror("nodename nor servname provided"),
    ):
        with pytest.raises(UnsafeUserUrlError, match="could not resolve"):
            validate_user_base_url("https://nonexistent.invalid/v1")


@pytest.mark.unit
def test_rejects_hostname_resolving_to_metadata_ip_via_dns():
    # Even if a hostname looks innocent, if DNS hands us 169.254.169.254
    # we must refuse — defense-in-depth at dispatch time.
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
        with pytest.raises(UnsafeUserUrlError, match="blocked address"):
            validate_user_base_url("https://innocent.example.com/v1")


@pytest.mark.unit
def test_rejects_hostname_resolving_to_ipv6_loopback_via_dns():
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("::1")):
        with pytest.raises(UnsafeUserUrlError, match="blocked address"):
            validate_user_base_url("https://aaaa-only.example.com/v1")


# pinned_post — single-resolve, IP-pinned outbound HTTP


class _StubResponse:
    """Drop-in for a ``requests.Response`` that ``Session.send`` returns."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.text = ""
        self.headers = {"Content-Type": "application/json"}


def _capture_send(monkeypatch):
    """Replace ``requests.Session.send`` with a capturing stub.

    Returns a dict that fills with ``prepared`` (the
    ``PreparedRequest``) and ``send_kwargs`` once a request is issued,
    plus ``adapters`` so callers can inspect what was mounted on the
    session.
    """
    captured: dict = {}

    def _send(self, prepared, **kwargs):
        captured["prepared"] = prepared
        captured["send_kwargs"] = kwargs
        captured["adapters"] = dict(self.adapters)
        return _StubResponse()

    monkeypatch.setattr(requests.Session, "send", _send)
    return captured


@pytest.mark.unit
def test_pinned_post_rewrites_host_to_resolved_ipv4(monkeypatch):
    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")):
        pinned_post(
            "https://api.openai.com/v1/chat/completions",
            json={"hi": True},
            headers={"Authorization": "Bearer sk-x"},
            timeout=5,
            allow_redirects=False,
        )

    prepared = captured["prepared"]
    assert prepared.url == "https://104.18.6.192/v1/chat/completions"
    # Host header carries the original hostname so vhost-routing and
    # SNI/cert verification target the right server.
    assert prepared.headers["Host"] == "api.openai.com"
    # Caller-supplied headers are preserved.
    assert prepared.headers["Authorization"] == "Bearer sk-x"
    # The body was sent as JSON.
    assert prepared.body == b'{"hi": true}'


@pytest.mark.unit
def test_pinned_post_brackets_ipv6_in_url(monkeypatch):
    captured = _capture_send(monkeypatch)
    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("2606:4700::6810:1234")
    ):
        pinned_post(
            "https://example.com/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
    assert (
        captured["prepared"].url == "https://[2606:4700::6810:1234]/v1/x"
    )
    assert captured["prepared"].headers["Host"] == "example.com"


@pytest.mark.unit
def test_pinned_post_preserves_explicit_port(monkeypatch):
    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        pinned_post(
            "https://api.example.com:8443/v1/test",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
    assert captured["prepared"].url == "https://93.184.216.34:8443/v1/test"
    # Host header keeps the original :port — proxies and vhost routers
    # rely on this, and SNI conventionally carries the bare hostname.
    assert captured["prepared"].headers["Host"] == "api.example.com:8443"


@pytest.mark.unit
def test_pinned_post_handles_ip_literal_url_without_dns(monkeypatch):
    """If the URL already has an IP literal, no DNS lookup happens."""

    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo") as gai:
        pinned_post(
            "https://93.184.216.34/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
        assert gai.call_count == 0
    assert captured["prepared"].url == "https://93.184.216.34/v1/x"
    assert captured["prepared"].headers["Host"] == "93.184.216.34"


@pytest.mark.unit
def test_pinned_post_resolves_dns_exactly_once(monkeypatch):
    """The whole point of the helper: one resolution, one connection.

    A DNS-rebinding attacker wins by getting a second ``getaddrinfo``
    call after the first one was validated. If this assertion ever
    fails, the SSRF guard has regressed.
    """

    captured = _capture_send(monkeypatch)
    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ) as gai:
        pinned_post(
            "https://api.openai.com/v1/chat/completions",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
        assert gai.call_count == 1
    assert captured["prepared"].url.startswith("https://104.18.6.192/")


@pytest.mark.unit
def test_pinned_post_mounts_pinned_adapter_for_https(monkeypatch):
    """For HTTPS, a custom adapter must be mounted that overrides
    ``server_hostname`` / ``assert_hostname`` so SNI and cert
    verification target the original hostname even though we connect
    to an IP literal.
    """

    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")):
        pinned_post(
            "https://api.openai.com/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )

    https_adapter = captured["adapters"]["https://"]
    # _PinnedHostAdapter is the symbol we expect; also check it carries
    # the original hostname so SNI/cert verification line up.
    assert type(https_adapter).__name__ == "_PinnedHostAdapter"
    assert https_adapter._server_hostname == "api.openai.com"


@pytest.mark.unit
def test_pinned_post_does_not_mount_https_adapter_for_http(monkeypatch):
    """For HTTP, no SNI/cert logic is needed — the default adapter
    should remain in place; only the URL rewrite + Host header matter."""

    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        pinned_post(
            "http://example.com/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
    https_adapter = captured["adapters"]["https://"]
    assert type(https_adapter).__name__ == "HTTPAdapter"


@pytest.mark.unit
def test_pinned_post_raises_for_blocked_dns_result(monkeypatch):
    """A hostname that resolves to a private IP must be rejected
    *before* any HTTP request is dispatched."""

    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
        with pytest.raises(UnsafeUserUrlError, match="blocked address"):
            pinned_post(
                "https://internal.example.com/v1/x",
                json={},
                headers={},
                timeout=5,
                allow_redirects=False,
            )
    assert "prepared" not in captured


@pytest.mark.unit
def test_pinned_post_raises_for_loopback_ip_literal(monkeypatch):
    captured = _capture_send(monkeypatch)
    with pytest.raises(UnsafeUserUrlError, match="blocked address"):
        pinned_post(
            "https://127.0.0.1/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
    assert "prepared" not in captured


@pytest.mark.unit
def test_pinned_post_raises_for_disallowed_scheme(monkeypatch):
    captured = _capture_send(monkeypatch)
    with pytest.raises(UnsafeUserUrlError, match="scheme"):
        pinned_post(
            "ftp://example.com/v1/x",
            json={},
            headers={},
            timeout=5,
            allow_redirects=False,
        )
    assert "prepared" not in captured


@pytest.mark.unit
def test_pinned_post_overrides_caller_supplied_host_header(monkeypatch):
    """If the caller passes their own Host header, the helper must
    still set it to the resolved hostname so the in-flight request
    doesn't disagree with what was validated."""

    captured = _capture_send(monkeypatch)
    with mock.patch("socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")):
        pinned_post(
            "https://api.openai.com/v1/x",
            json={},
            headers={"Host": "evil.example.com"},
            timeout=5,
            allow_redirects=False,
        )
    assert captured["prepared"].headers["Host"] == "api.openai.com"


# pinned_httpx_client — DNS-rebinding-safe httpx transport for SDK use


def _capture_httpx_handle_request(monkeypatch):
    """Patch ``httpx.HTTPTransport.handle_request`` to record the
    request reaching the parent transport, and return a fake response.

    The pinned transport's ``handle_request`` rewrites
    ``request.url.host`` and sets ``sni_hostname`` *before* delegating
    to ``super().handle_request``. Capturing what the parent sees
    gives us the actual values that would feed httpcore's connect
    (and thus what TCP would dial / SNI would advertise) without
    opening a real socket.
    """

    import httpx

    captured: dict = {}

    def fake_handle(self, request):
        captured["url"] = request.url
        captured["sni"] = request.extensions.get("sni_hostname")
        captured["host_header"] = request.headers.get("host")
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(
        "httpx.HTTPTransport.handle_request", fake_handle
    )
    return captured


@pytest.mark.unit
def test_pinned_httpx_client_returns_pinned_transport():
    """The factory must wire its transport in unchanged and bind it
    to the validated host and IP."""

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        assert isinstance(client._transport, _PinnedHTTPSTransport)
        assert client._transport._host == "api.example.com"
        assert client._transport._ip_netloc == "104.18.6.192"
    finally:
        client.close()


@pytest.mark.unit
def test_pinned_httpx_client_disables_redirects():
    """SSRF guard only inspects the supplied URL — following 3xx would
    let a hostile upstream bounce the in-network request to an
    internal address."""

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        assert client.follow_redirects is False
    finally:
        client.close()


@pytest.mark.unit
def test_pinned_httpx_transport_rewrites_url_to_validated_ip(monkeypatch):
    """The core invariant: every request reaching httpcore has its URL
    host pointed at the IP literal we validated, so TCP dials that IP
    rather than triggering a fresh DNS resolution."""

    captured = _capture_httpx_handle_request(monkeypatch)

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        client.get("https://api.example.com/v1/test")
    finally:
        client.close()

    assert captured["url"].host == "104.18.6.192"


@pytest.mark.unit
def test_pinned_httpx_transport_sets_sni_for_original_hostname(monkeypatch):
    """TLS SNI / cert verification must use the original hostname; the
    transport sets it via the ``sni_hostname`` extension that
    httpcore forwards to ``start_tls``'s ``server_hostname``."""

    captured = _capture_httpx_handle_request(monkeypatch)

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        client.get("https://api.example.com/v1/test")
    finally:
        client.close()

    assert captured["sni"] == b"api.example.com"


@pytest.mark.unit
def test_pinned_httpx_transport_preserves_host_header(monkeypatch):
    """``Host`` is auto-set by ``httpx.Request._prepare`` from the URL
    netloc *before* our transport rewrites the URL host. The header
    must still carry the original hostname."""

    captured = _capture_httpx_handle_request(monkeypatch)

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        client.get("https://api.example.com/v1/test")
    finally:
        client.close()

    assert captured["host_header"] == "api.example.com"


@pytest.mark.unit
def test_pinned_httpx_client_closes_dns_rebinding_window(monkeypatch):
    """The TOCTOU lock-in test: validate against a public IP, then
    have DNS rebind to a private (loopback) IP, then send a request.
    The transport must dial the *first* validated IP — not the
    rebound one — guaranteeing no second DNS lookup interferes."""

    captured = _capture_httpx_handle_request(monkeypatch)

    # First lookup (at validation time) returns a public IP.
    public = _addrinfo("104.18.6.192")
    # Subsequent lookups (which the transport must NEVER trigger)
    # would return loopback if a hostile resolver flipped them.
    private = _addrinfo("127.0.0.1")

    getaddrinfo_calls: list = []

    def fake_getaddrinfo(*args, **kwargs):
        getaddrinfo_calls.append((args, kwargs))
        # First call = validation; everything after = post-rebind.
        return public if len(getaddrinfo_calls) == 1 else private

    monkeypatch.setattr("socket.getaddrinfo", fake_getaddrinfo)

    client = pinned_httpx_client("https://api.attacker.example/v1")
    try:
        client.get("https://api.attacker.example/v1/test")
    finally:
        client.close()

    # Whatever happens below the transport, the URL handed to
    # httpcore must be the IP from the *first* getaddrinfo call.
    assert captured["url"].host == "104.18.6.192", (
        "pinned transport must dial the IP validated at construction, "
        "not whatever DNS returns at request time"
    )


@pytest.mark.unit
def test_pinned_httpx_client_rejects_blocked_dns_result():
    """If the validation lookup itself returns a private IP, the
    factory must refuse to construct a client at all."""

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")
    ):
        with pytest.raises(UnsafeUserUrlError, match="link-local"):
            pinned_httpx_client("https://api.attacker.example/v1")


@pytest.mark.unit
def test_pinned_httpx_client_rejects_loopback_literal():
    """An IP literal in the supplied URL goes through the same guard
    even when DNS isn't called."""

    with pytest.raises(UnsafeUserUrlError):
        pinned_httpx_client("http://127.0.0.1:8080/v1")


@pytest.mark.unit
def test_pinned_httpx_transport_refuses_unexpected_host(monkeypatch):
    """Defense in depth: if the SDK ever rewrites the request URL to a
    different host between Request construction and dial, the
    transport refuses rather than silently dialing the validated IP
    with a different host's credentials."""

    import httpx

    with mock.patch(
        "socket.getaddrinfo", return_value=_addrinfo("104.18.6.192")
    ):
        client = pinned_httpx_client("https://api.example.com/v1")
    try:
        with pytest.raises(UnsafeUserUrlError, match="refused request"):
            client.get("https://other.example.com/v1/test")
    except httpx.RequestError:
        # Some httpx versions may wrap the transport error; accept
        # either path so long as the request didn't succeed.
        pass
    finally:
        client.close()
