#!/usr/bin/env python3
"""Boot a Droplet from a DocsGPT 1-Click snapshot and check it the way a customer would meet it.

Standard library only, so it runs on a bare CI runner::

    DIGITALOCEAN_TOKEN=... python3 deployment/digitalocean/smoke_test.py --snapshot 123456789

It creates a throwaway SSH key and Droplet, waits for the first boot to finish, then checks:

* https://<IP> answers with a certificate the system trusts (Let's Encrypt's IP certificate);
* only ports 22, 80 and 443 answer from outside;
* the login message shows the address and the access token, and the token opens the API;
* a document uploaded with the token is ingested and an answer cites it;
* after ``docsgpt up --accounts``, the first admin signs in through Keycloak (setting a new
  password, as the first sign-in asks) and DocsGPT gives them the admin role;
* ``docsgpt backup`` writes an archive holding the Keycloak database.

The Droplet and the key are deleted at the end, pass or fail, unless ``--keep`` is given.
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

API = "https://api.digitalocean.com/v2"
CLOSED_PORTS = (5432, 6379, 7091, 8080, 9000)
MAGIC = "The DocsGPT smoke test's secret ingredient is cardamom-7421."


class Fatal(Exception):
    """A failure that waiting longer cannot fix."""


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class DigitalOcean:
    """The few DigitalOcean API calls the test needs."""

    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        request = urllib.request.Request(
            f"{API}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}


def ssh(key: Path, address: str, command: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-i", str(key), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", f"root@{address}", command],
        capture_output=True, text=True, timeout=timeout,
    )


def remote(key: Path, address: str, command: str, timeout: int = 900) -> str:
    """Run ``command`` as root on the Droplet and return its output, failing on a non-zero exit."""
    result = ssh(key, address, command, timeout)
    if result.returncode != 0:
        raise AssertionError(f"`{command}` exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    return result.stdout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102 - redirects are followed by hand
        return None


class Browser:
    """Cookies and certificate checks like a browser; redirects are returned, not followed."""

    def __init__(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            NoRedirect,
        )

    def open(
        self, url: str, data: Optional[bytes] = None, headers: Optional[dict] = None, method: Optional[str] = None
    ) -> tuple[int, dict, str]:
        request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read().decode("utf-8", "replace")

    def json(self, url: str, token: str, body: Optional[Any] = None, method: Optional[str] = None) -> Any:
        headers = {"Authorization": f"Bearer {token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, _, text = self.open(url, data, headers, method)
        if status != 200:
            raise AssertionError(f"{method or ('POST' if data else 'GET')} {url} answered {status}: {text[:500]}")
        return json.loads(text)


def multipart(fields: dict, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def wait_for(what: str, check, timeout: int, interval: int = 10):
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        try:
            result = check()
            if result:
                return result
        except Fatal:
            raise
        except Exception as exc:  # noqa: BLE001 - keep trying until the deadline
            last = exc
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}" + (f": {last}" if last else ""))


def check_https(base: str) -> None:
    def answers() -> bool:
        status, _, body = Browser().open(f"{base}/api/health")
        return status == 200
    wait_for(f"{base} with a trusted certificate", answers, timeout=600)
    log(f"{base} answers with a certificate this machine trusts")


def check_ports(address: str) -> None:
    for port in CLOSED_PORTS:
        with socket.socket() as probe:
            probe.settimeout(5)
            if probe.connect_ex((address, port)) == 0:
                raise AssertionError(f"port {port} answers from outside")
    log(f"ports {', '.join(map(str, CLOSED_PORTS))} are closed from outside")


def check_ingest_and_answer(base: str, token: str) -> None:
    browser = Browser()
    name = f"smoke-{uuid.uuid4().hex[:8]}"
    body, content_type = multipart({"name": name}, "smoke.txt", (MAGIC + "\n") * 3)
    status, _, text = browser.open(
        f"{base}/api/upload", body, {"Authorization": f"Bearer {token}", "Content-Type": content_type}
    )
    assert status == 200, f"upload answered {status}: {text[:500]}"
    task_id = json.loads(text)["task_id"]

    def ingested() -> bool:
        state = browser.json(f"{base}/api/task_status?task_id={task_id}", token)
        if state.get("status") == "FAILURE":
            raise Fatal(f"ingest failed: {state}")
        return state.get("status") == "SUCCESS"
    wait_for("the upload to be ingested", ingested, timeout=600)
    sources = browser.json(f"{base}/api/sources", token)
    source = next(s for s in sources if s.get("name") == name)
    answer = browser.json(
        f"{base}/api/answer", token,
        {"question": "What is the smoke test's secret ingredient?", "active_docs": str(source["id"]),
         "isNoneDoc": False},
    )
    cited = json.dumps(answer.get("sources", []))
    assert "cardamom-7421" in cited or "cardamom" in answer.get("answer", "").lower(), answer
    log(f"ingested a document and got an answer citing it: {answer.get('answer', '')[:120]!r}")


def _form(page: str) -> tuple[str, dict]:
    """The first form's action and its hidden fields, from a Keycloak page."""
    match = re.search(r'<form[^>]*action="([^"]+)"', page)
    if not match:
        raise AssertionError(f"no form on the Keycloak page:\n{page[:2000]}")
    hidden = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page))
    return html.unescape(match.group(1)), hidden


def check_accounts(base: str, admin_password: str) -> None:
    browser = Browser()
    status, headers, _ = browser.open(f"{base}/api/auth/oidc/login")
    assert status == 302, f"/api/auth/oidc/login answered {status}"
    location = headers["Location"]
    assert location.startswith(f"{base}/auth/realms/docsgpt/"), location

    status, headers, page = browser.open(location)
    assert status == 200, f"the Keycloak sign-in page answered {status}"
    new_password = f"Smoke-{uuid.uuid4().hex[:12]}"
    fields = {"username": "admin", "password": admin_password}
    for _ in range(5):
        action, hidden = _form(page)
        names = set(re.findall(r'name="([^"]+)"', page))
        values = {**hidden, **{k: v for k, v in fields.items() if k in names}}
        if "password-new" in names:
            values.update({"password-new": new_password, "password-confirm": new_password})
        for key, value in (("email", "admin@example.com"), ("firstName", "DocsGPT"), ("lastName", "Admin")):
            if key in names and key not in values:
                values[key] = value
        status, headers, page = browser.open(
            action, urllib.parse.urlencode(values).encode(), {"Content-Type": "application/x-www-form-urlencoded"}
        )
        if status == 302:
            break
        assert status == 200, f"Keycloak answered {status}:\n{page[:2000]}"
    else:
        raise AssertionError("Keycloak never sent the browser back to DocsGPT")

    callback = headers["Location"]
    assert callback.startswith(f"{base}/api/auth/oidc/callback"), callback
    status, headers, _ = browser.open(callback)
    assert status == 302, f"the callback answered {status}"
    fragment = urllib.parse.urlsplit(headers["Location"]).fragment
    assert fragment.startswith("oidc_code="), f"the callback sent the browser to {headers['Location']}"
    code = fragment.removeprefix("oidc_code=")
    session = browser.json(f"{base}/api/auth/oidc/token", "", {"code": code})["token"]
    me = browser.json(f"{base}/api/user/me", session)
    assert "admin" in json.dumps(me.get("roles", me)), me
    log(f"the first admin signed in through Keycloak and is an admin in DocsGPT: {me}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshot", required=True, help="the snapshot (image) id to boot")
    parser.add_argument("--region", default="nyc3")
    parser.add_argument("--size", default="s-2vcpu-4gb")
    parser.add_argument("--keep", action="store_true", help="leave the Droplet running for a look around")
    parser.add_argument("--skip-accounts", action="store_true", help="skip the Keycloak checks")
    args = parser.parse_args()
    token = os.environ.get("DIGITALOCEAN_TOKEN") or os.environ.get("DIGITALOCEAN_ACCESS_TOKEN")
    if not token:
        parser.error("set DIGITALOCEAN_TOKEN")
    do = DigitalOcean(token)

    workdir = Path(tempfile.mkdtemp(prefix="docsgpt-smoke-"))
    key = workdir / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    name = f"docsgpt-smoke-{uuid.uuid4().hex[:8]}"
    key_id = do.call("POST", "/account/keys", {"name": name, "public_key": (workdir / "id_ed25519.pub").read_text()})[
        "ssh_key"]["id"]
    droplet_id = None
    try:
        droplet_id = do.call("POST", "/droplets", {
            "name": name, "region": args.region, "size": args.size, "image": int(args.snapshot),
            "ssh_keys": [key_id], "tags": ["docsgpt-smoke-test"],
        })["droplet"]["id"]
        log(f"created Droplet {droplet_id} ({name})")

        def public_address() -> Optional[str]:
            droplet = do.call("GET", f"/droplets/{droplet_id}")["droplet"]
            if droplet["status"] != "active":
                return None
            return next((n["ip_address"] for n in droplet["networks"]["v4"] if n["type"] == "public"), None)
        address = wait_for("the Droplet to be active", public_address, timeout=600)
        base = f"https://{address}"
        log(f"Droplet is active at {address}")

        def set_up() -> bool:
            result = ssh(key, address, "echo ready; test -f /opt/docsgpt/install.json && echo installed", 60)
            return "installed" in result.stdout
        wait_for("the first boot to set DocsGPT up", set_up, timeout=1500, interval=15)
        log("the first boot finished:\n" + remote(key, address, "tail -n 25 /var/log/docsgpt-onboot.log"))

        check_https(base)
        check_ports(address)
        motd = remote(key, address, "run-parts /etc/update-motd.d/ 2>/dev/null | sed -n '/DocsGPT on/,$p'")
        access_token = remote(key, address, "docsgpt token").strip()
        assert base in motd and access_token in motd, motd
        log("the login message shows the address and the access token")
        assert Browser().open(f"{base}/api/user/me")[0] == 401, "the API must refuse a request without the token"
        check_ingest_and_answer(base, access_token)

        if not args.skip_accounts:
            log("turning user accounts on ...")
            log(remote(key, address, "docsgpt up --yes --accounts --timeout 900 2>&1 | tail -n 8"))
            env = remote(key, address, "cat /opt/docsgpt/.env")
            password = re.search(r"^KEYCLOAK_ADMIN_PASSWORD=(.+)$", env, re.M).group(1)
            check_https(base)
            check_ports(address)
            check_accounts(base, password)
            log(remote(key, address, "docsgpt backup 2>&1 | tail -n 3"))
            listing = remote(key, address, "tar tzf $(ls -t /opt/docsgpt/backups/*.tar.gz | head -n 1)")
            assert "databases/keycloak.sql" in listing, listing
            log("the backup holds the Keycloak database")

        log(remote(key, address, "free -m; docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'"))
        log("all checks passed")
        return 0
    finally:
        if args.keep and droplet_id:
            log(f"kept Droplet {droplet_id}; log in with: ssh -i {key} root@<its address>")
        elif droplet_id:
            do.call("DELETE", f"/droplets/{droplet_id}")
            log(f"deleted Droplet {droplet_id}")
        # The Droplet already holds the key, so the account copy goes either way.
        do.call("DELETE", f"/account/keys/{key_id}")


if __name__ == "__main__":
    sys.exit(main())
