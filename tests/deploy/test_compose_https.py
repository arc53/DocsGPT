"""Caddy and the accounts profile (Keycloak) in the standalone Compose file, which ``docsgpt up`` runs.

The Caddyfile and the Keycloak realm are written inline in the Compose file, so they are checked here as
Compose resolves them; where a Docker daemon and the Caddy image are at hand, Caddy itself parses the result.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from docsgpt.deploy import stack

from .test_compose_files import DEPLOYMENT, _load, _resolved

STANDALONE = DEPLOYMENT / "docker-compose-standalone.yaml"
IP_ENV = "INTERNAL_KEY=i\nCOMPOSE_PROFILES=https\nDOCSGPT_DOMAIN=8.8.8.8\nDOCSGPT_TLS=ip\n"
ACCOUNTS_ENV = (
    "INTERNAL_KEY=i\nCOMPOSE_PROFILES=https,accounts\nDOCSGPT_DOMAIN=8.8.8.8\nDOCSGPT_TLS=ip\n"
    "DOCSGPT_ACCOUNTS=on\nOIDC_CLIENT_SECRET=client-secret\nKEYCLOAK_ADMIN_PASSWORD=first-password\n"
    "POSTGRES_PASSWORD=pg\n"
)


def _unescape(value: str) -> str:
    """``docker compose config`` writes a literal ``$`` as ``$$`` so its output stays loadable."""
    return value.replace("$$", "$")


def _env_value(service: dict, name: str) -> str:
    environment = service["environment"]
    if isinstance(environment, dict):
        return environment[name]
    for entry in environment:
        key, _, value = entry.partition("=")
        if key == name:
            return value
    raise KeyError(name)


@pytest.mark.unit
class TestDeclared:
    def test_keycloak_is_opt_in_and_never_published(self):
        services = _load(STANDALONE)["services"]
        for name in ("keycloak", "keycloak-db"):
            assert services[name]["profiles"] == [stack.ACCOUNTS_PROFILE], name
            assert "ports" not in services[name], name

    def test_the_realm_redirects_relative_to_its_own_address(self):
        """Keycloak resolves a relative redirect against its public origin, so a move to a domain needs no edit."""
        realm = json.loads(_env_value(_load(STANDALONE)["services"]["keycloak"], "DOCSGPT_REALM"))
        client = next(c for c in realm["clients"] if c["clientId"] == stack.KEYCLOAK_CLIENT_ID)
        assert client["redirectUris"] == ["/api/auth/oidc/callback"]
        assert client["rootUrl"] == ""
        assert client["publicClient"] is False and client["attributes"]["pkce.code.challenge.method"] == "S256"
        assert client["secret"] == "$${DOCSGPT_OIDC_CLIENT_SECRET}", "Keycloak fills it in, not Compose"

    def test_the_realm_makes_the_first_user_an_admin_with_a_temporary_password(self):
        realm = json.loads(_env_value(_load(STANDALONE)["services"]["keycloak"], "DOCSGPT_REALM"))
        assert realm["realm"] == stack.KEYCLOAK_REALM
        assert realm["registrationAllowed"] is False and realm["bruteForceProtected"] is True
        admin = next(u for u in realm["users"] if u["username"] == stack.KEYCLOAK_ADMIN_USER)
        assert admin["groups"] == [stack.KEYCLOAK_ADMIN_GROUP]
        assert admin["credentials"] == [
            {"type": "password", "value": "$${DOCSGPT_ADMIN_PASSWORD}", "temporary": True}
        ]
        mapper = realm["clients"][0]["protocolMappers"][0]
        assert mapper["protocolMapper"] == "oidc-group-membership-mapper"
        assert mapper["config"]["claim.name"] == "groups" and mapper["config"]["full.path"] == "false"


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("docker") is None, reason="needs the docker command (no daemon)")
class TestResolved:
    def test_a_domain_keeps_caddys_own_certificates_and_no_keycloak(self, tmp_path):
        dotenv = "INTERNAL_KEY=i\nCOMPOSE_PROFILES=https\nDOCSGPT_DOMAIN=docs.example.com\n"
        services = _resolved(tmp_path, STANDALONE, dotenv=dotenv)["services"]
        caddy = services["caddy"]["environment"]
        assert caddy["DOCSGPT_TLS"] == "domain" and caddy["DOCSGPT_ACCOUNTS"] == "off"
        assert "keycloak" not in services and "keycloak-db" not in services

    def test_an_ip_address_asks_for_the_shortlived_profile(self, tmp_path):
        caddy = _resolved(tmp_path, STANDALONE, dotenv=IP_ENV)["services"]["caddy"]["environment"]
        assert caddy["DOCSGPT_TLS"] == "ip" and caddy["DOCSGPT_DOMAIN"] == "8.8.8.8"
        caddyfile = _unescape(caddy["CADDYFILE"])
        assert "profile shortlived" in caddyfile and "issuer internal" in caddyfile
        assert "import tls-{$DOCSGPT_TLS}" in caddyfile
        assert "default_sni {$DOCSGPT_DOMAIN}" in caddyfile, "browsers send no SNI to an IP address"

    def test_accounts_put_keycloak_behind_auth_on_the_same_address(self, tmp_path):
        services = _resolved(tmp_path, STANDALONE, dotenv=ACCOUNTS_ENV)["services"]
        keycloak = services["keycloak"]["environment"]
        assert keycloak["KC_HOSTNAME"] == "https://8.8.8.8/auth"
        assert keycloak["KC_HTTP_RELATIVE_PATH"] == "/auth"
        assert keycloak["KC_DB_PASSWORD"] == "pg"
        assert keycloak["DOCSGPT_OIDC_CLIENT_SECRET"] == "client-secret"
        assert keycloak["DOCSGPT_ADMIN_PASSWORD"] == "first-password"
        assert services["caddy"]["environment"]["DOCSGPT_ACCOUNTS"] == "on"
        assert services["keycloak"]["depends_on"]["keycloak-db"]["condition"] == "service_completed_successfully"


def _daemon_with(image: str) -> bool:
    if shutil.which("docker") is None:
        return False
    found = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=30)
    return found.returncode == 0


@pytest.mark.unit
@pytest.mark.skipif(not _daemon_with("caddy:2-alpine"), reason="needs a Docker daemon with caddy:2-alpine pulled")
class TestCaddyParses:
    @pytest.mark.parametrize(
        "dotenv",
        [IP_ENV, ACCOUNTS_ENV, "INTERNAL_KEY=i\nCOMPOSE_PROFILES=https\nDOCSGPT_DOMAIN=docs.example.com\n"],
        ids=["ip", "accounts", "domain"],
    )
    def test_caddy_adapts_the_caddyfile(self, tmp_path: Path, dotenv):
        caddy = _resolved(tmp_path, STANDALONE, dotenv=dotenv)["services"]["caddy"]["environment"]
        (tmp_path / "Caddyfile").write_text(_unescape(caddy["CADDYFILE"]), encoding="utf-8")
        result = subprocess.run(
            ["docker", "run", "--rm", "-v", f"{tmp_path / 'Caddyfile'}:/etc/caddy/Caddyfile:ro",
             *[arg for key in ("DOCSGPT_DOMAIN", "DOCSGPT_TLS", "DOCSGPT_ACCOUNTS")
               for arg in ("-e", f"{key}={caddy[key]}")],
             "caddy:2-alpine", "caddy", "adapt", "--config", "/etc/caddy/Caddyfile"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        config = json.loads(result.stdout)
        assert config["apps"]["http"]["servers"]["srv0"]["tls_connection_policies"][0]["default_sni"] == (
            caddy["DOCSGPT_DOMAIN"]
        )
        policies = config["apps"].get("tls", {}).get("automation", {}).get("policies", [])
        if caddy["DOCSGPT_TLS"] == "ip":
            assert policies[0]["issuers"] == [{"module": "acme", "profile": "shortlived"}, {"module": "internal"}]
        else:
            assert not policies, "a domain keeps Caddy's default issuers"
        routes = json.dumps(config["apps"]["http"]["servers"])
        assert ("keycloak:8080" in routes) is (caddy["DOCSGPT_ACCOUNTS"] == "on")
