"""Fuzz the SSRF guard for user-supplied base URLs (docsgpt.security.safe_url).

DNS is replaced by a resolver that answers from the fuzz input, the way a
hostile DNS server would, while still treating IP-literal names the way the
system resolver does (``127.1``, ``0x7f.0.0.1``, ``2130706433``).

Invariants checked on every input:

* the guard raises nothing but ``UnsafeUserUrlError``;
* an accepted URL is http(s) and has a host;
* no address an accepted URL can reach is loopback, private, link-local,
  CGNAT, multicast, reserved or unspecified (checked against explicit
  networks, not the guard's own helper), and no blocked name is accepted;
* urllib3 (what ``requests`` dials) reads the same host the guard checked.
"""

from __future__ import annotations

import ipaddress
import socket
import sys

import atheris

with atheris.instrument_imports():
    import urllib3
    from docsgpt.security import safe_url

# Every address the guard promises never to dial, spelled out independently of
# ``safe_url._is_blocked_ip`` so a regression there is caught.
_FORBIDDEN = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]
_FORBIDDEN_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "metadata.google.internal"}

_SCHEMES = ["http", "https", "HTTP", "hTtPs", "ftp", "file", "gopher", "", "http:", "javascript"]
_HOSTS = [
    "localhost",
    "LOCALHOST.",
    "metadata.google.internal",
    "127.0.0.1",
    "127.1",
    "0x7f.1",
    "0177.0.0.1",
    "2130706433",
    "0",
    "[::1]",
    "[::ffff:127.0.0.1]",
    "[::ffff:7f00:1]",
    "[fe80::1%25eth0]",
    "[fd00:ec2::254]",
    "169.254.169.254",
    "100.100.100.200",
    "10.0.0.1",
    "8.8.8.8",
    "[2001:4860:4860::8888]",
    "example.com",
    "xn--bcher-kva.example",
    "bücher.example",
    "127\u30020\u30020\u30021",
    "127\uff0e0\uff0e0\uff0e1",
    "ｌｏｃａｌｈｏｓｔ",
]
_GLUE = ["@", ":", "\\", "/", "#", "?", "%", "%2e", "[", "]", " ", "\t", "\n", ".", "\u3002", ";", ""]


class _Answer:
    """What the fake resolver returns for names that are not IP literals."""

    records: list[str] = []
    fail = False


def _ip_literal(host: str) -> str | None:
    """The address the system resolver would return for an IP-literal ``host``, if it is one."""
    try:
        return socket.inet_ntoa(socket.inet_aton(host))
    except (OSError, ValueError):
        pass
    try:
        return socket.inet_ntop(socket.AF_INET6, socket.inet_pton(socket.AF_INET6, host.split("%", 1)[0]))
    except (OSError, ValueError):
        return None


def _fake_getaddrinfo(host, port, *args, **kwargs):
    """Resolve IP literals as libc does; answer everything else from the fuzz input."""
    if not isinstance(host, str):
        raise socket.gaierror(socket.EAI_NONAME, "bad host type")
    host.encode("idna")  # libc refuses names the IDNA codec rejects; so does socket.getaddrinfo.
    literal = _ip_literal(host)
    answers = [literal] if literal else list(_Answer.records)
    if _Answer.fail and not literal:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    out = []
    for ip in answers:
        if ":" in ip:
            out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
        else:
            out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
    return out


socket.getaddrinfo = _fake_getaddrinfo
# No operator allowlist: every blocked address must stay blocked.
safe_url._allowlist = lambda: (set(), [])


def _forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether ``ip`` (or the IPv4 address it maps) is in a range the guard must refuse."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in _FORBIDDEN)


def _random_ip(fdp: atheris.FuzzedDataProvider) -> str:
    """An IPv4 or IPv6 address chosen by the input, with scope ids now and then."""
    if fdp.ConsumeBool():
        return str(ipaddress.IPv4Address(fdp.ConsumeIntInRange(0, 2**32 - 1)))
    text = str(ipaddress.IPv6Address(fdp.ConsumeIntInRange(0, 2**128 - 1)))
    return f"{text}%lo0" if fdp.ConsumeIntInRange(0, 7) == 0 else text


def _build_url(fdp: atheris.FuzzedDataProvider) -> str:
    """A URL assembled from tricky pieces, or a raw string from the input."""
    if fdp.ConsumeIntInRange(0, 4) == 0:
        return fdp.ConsumeUnicodeNoSurrogates(256)
    parts = [fdp.PickValueInList(_SCHEMES), "://"]
    for _ in range(fdp.ConsumeIntInRange(1, 5)):
        choice = fdp.ConsumeIntInRange(0, 3)
        if choice == 0:
            parts.append(fdp.PickValueInList(_HOSTS))
        elif choice == 1:
            parts.append(fdp.PickValueInList(_GLUE))
        elif choice == 2:
            parts.append(_random_ip(fdp).split("%", 1)[0])
        else:
            parts.append(fdp.ConsumeUnicodeNoSurrogates(16))
    if fdp.ConsumeBool():
        parts.append(f":{fdp.ConsumeIntInRange(0, 70000)}")
    parts.append(fdp.PickValueInList(["", "/", "/v1", "/v1?x=1#f", "\\@evil.example/", "?@127.0.0.1"]))
    return "".join(parts)


def _urllib3_host(url: str) -> str | None:
    """The host urllib3 would hand to the resolver for ``url``, without brackets or zone id."""
    try:
        host = urllib3.util.parse_url(url).host
    except urllib3.exceptions.LocationParseError:
        return None
    if host is None:
        return None
    return host.strip("[]").split("%", 1)[0].lower()


def TestOneInput(data: bytes) -> None:
    """Run the guard on one URL and check what it accepted."""
    fdp = atheris.FuzzedDataProvider(data)
    _Answer.fail = fdp.ConsumeIntInRange(0, 9) == 0
    _Answer.records = [_random_ip(fdp) for _ in range(fdp.ConsumeIntInRange(0, 3))]
    url = _build_url(fdp)

    try:
        host, ip, parts = safe_url._validate_and_pick_ip(url)
    except safe_url.UnsafeUserUrlError:
        return

    assert parts.scheme.lower() in ("http", "https"), url
    assert host, url
    assert not _forbidden(ip), (url, ip)
    assert host.rstrip(".") not in _FORBIDDEN_NAMES, url

    dialed = _urllib3_host(url)
    assert dialed is not None, url
    literal = _ip_literal(dialed)
    if literal is not None:
        assert not _forbidden(ipaddress.ip_address(literal)), (url, dialed)
    else:
        assert dialed.rstrip(".") not in _FORBIDDEN_NAMES, (url, dialed)
        # The name urllib3 dials resolves to the records the guard checked.
        assert all(not _forbidden(ipaddress.ip_address(r.split("%", 1)[0])) for r in _Answer.records), url


def main() -> None:
    """Start the fuzzer."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
