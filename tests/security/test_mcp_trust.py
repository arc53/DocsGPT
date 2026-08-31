"""Tests for MCP pre-execution trust verification (issue #2501)."""

from unittest.mock import patch

import pytest

from application.security.mcp_trust import (
    AllowlistTrustVerifier,
    MCPTrustBlockedError,
    TrustContext,
    TrustResult,
    TrustVerdict,
    enforce_mcp_trust,
    get_trust_verifier,
    set_trust_verifier,
    verify_mcp_trust,
)


@pytest.fixture(autouse=True)
def _clear_custom_verifier():
    """Isolate process-wide verifier state between tests."""
    set_trust_verifier(None)
    yield
    set_trust_verifier(None)


def _ctx(uri="https://mcp.example.com/sse", action="search", **kwargs):
    return TrustContext(
        server_uri=uri,
        action_name=action,
        user_id="user-1",
        **kwargs,
    )


@pytest.mark.unit
class TestAllowlistTrustVerifier:
    def test_empty_allowlist_warns(self):
        verifier = AllowlistTrustVerifier(allowed=[], blocked=[])
        result = verifier.verify(_ctx())
        assert result.verdict == TrustVerdict.WARNED
        assert "no allowlist" in result.reason.lower()

    def test_allowlist_exact_uri(self):
        verifier = AllowlistTrustVerifier(
            allowed=["https://mcp.example.com/sse"],
        )
        result = verifier.verify(_ctx("https://mcp.example.com/sse"))
        assert result.verdict == TrustVerdict.ALLOWED

    def test_allowlist_matches_hostname(self):
        verifier = AllowlistTrustVerifier(allowed=["mcp.example.com"])
        result = verifier.verify(_ctx("https://mcp.example.com/v1"))
        assert result.verdict == TrustVerdict.ALLOWED

    def test_allowlist_blocks_unknown(self):
        verifier = AllowlistTrustVerifier(allowed=["trusted.example.com"])
        result = verifier.verify(_ctx("https://evil.example.com"))
        assert result.verdict == TrustVerdict.BLOCKED
        assert "not on the allowlist" in result.reason

    def test_blocklist_wins(self):
        verifier = AllowlistTrustVerifier(
            allowed=["evil.example.com"],
            blocked=["evil.example.com"],
        )
        result = verifier.verify(_ctx("https://evil.example.com/mcp"))
        assert result.verdict == TrustVerdict.BLOCKED
        assert "blocklist" in result.reason

    def test_empty_uri_blocked(self):
        verifier = AllowlistTrustVerifier(allowed=["x"])
        result = verifier.verify(_ctx(""))
        assert result.verdict == TrustVerdict.BLOCKED


@pytest.mark.unit
class TestVerifyMcpTrust:
    def test_disabled_allows(self):
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_VERIFICATION_ENABLED = False
            result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.ALLOWED
        assert "disabled" in result.reason.lower()

    def test_enabled_uses_allowlist_from_settings(self):
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_VERIFICATION_ENABLED = True
            mock_settings.MCP_TRUST_ALLOWED_SERVERS = "good.example.com"
            mock_settings.MCP_TRUST_BLOCKED_SERVERS = None
            mock_settings.MCP_TRUST_FAIL_OPEN = True
            set_trust_verifier(None)
            result = verify_mcp_trust(_ctx("https://good.example.com/mcp"))
            assert result.verdict == TrustVerdict.ALLOWED
            blocked = verify_mcp_trust(_ctx("https://bad.example.com/mcp"))
            assert blocked.verdict == TrustVerdict.BLOCKED

    def test_custom_verifier_preferred(self):
        class AlwaysBlock:
            def verify(self, context):
                return TrustResult(
                    verdict=TrustVerdict.BLOCKED,
                    reason="custom block",
                )

        set_trust_verifier(AlwaysBlock())
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_VERIFICATION_ENABLED = False
            mock_settings.MCP_TRUST_FAIL_OPEN = True
            result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.BLOCKED
        assert result.reason == "custom block"

    def test_async_verifier_supported(self):
        class AsyncAllow:
            async def verify(self, context):
                return TrustResult(
                    verdict=TrustVerdict.ALLOWED,
                    reason="async ok",
                )

        set_trust_verifier(AsyncAllow())
        result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.ALLOWED
        assert result.reason == "async ok"

    def test_verifier_exception_fail_open(self):
        class Boom:
            def verify(self, context):
                raise RuntimeError("backend down")

        set_trust_verifier(Boom())
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_FAIL_OPEN = True
            result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.WARNED
        assert "fail-open" in result.reason

    def test_verifier_exception_fail_closed(self):
        class Boom:
            def verify(self, context):
                raise RuntimeError("backend down")

        set_trust_verifier(Boom())
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_FAIL_OPEN = False
            result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.BLOCKED
        assert "fail-closed" in result.reason

    def test_invalid_result_type_blocked(self):
        class Bad:
            def verify(self, context):
                return "yes"

        set_trust_verifier(Bad())
        result = verify_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.BLOCKED
        assert "invalid result" in result.reason


@pytest.mark.unit
class TestEnforceMcpTrust:
    def test_allowed_returns_result(self):
        set_trust_verifier(
            type(
                "V",
                (),
                {
                    "verify": lambda self, ctx: TrustResult(
                        verdict=TrustVerdict.ALLOWED, reason="ok"
                    )
                },
            )()
        )
        result = enforce_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.ALLOWED

    def test_blocked_raises(self):
        set_trust_verifier(
            type(
                "V",
                (),
                {
                    "verify": lambda self, ctx: TrustResult(
                        verdict=TrustVerdict.BLOCKED, reason="nope"
                    )
                },
            )()
        )
        with pytest.raises(MCPTrustBlockedError, match="nope"):
            enforce_mcp_trust(_ctx())

    def test_warn_proceeds_by_default(self):
        set_trust_verifier(
            type(
                "V",
                (),
                {
                    "verify": lambda self, ctx: TrustResult(
                        verdict=TrustVerdict.WARNED, reason="soft"
                    )
                },
            )()
        )
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_ON_WARN = "proceed"
            result = enforce_mcp_trust(_ctx())
        assert result.verdict == TrustVerdict.WARNED

    def test_warn_can_block(self):
        set_trust_verifier(
            type(
                "V",
                (),
                {
                    "verify": lambda self, ctx: TrustResult(
                        verdict=TrustVerdict.WARNED, reason="soft"
                    )
                },
            )()
        )
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_ON_WARN = "block"
            with pytest.raises(MCPTrustBlockedError, match="soft"):
                enforce_mcp_trust(_ctx())


@pytest.mark.unit
class TestGetTrustVerifier:
    def test_none_when_disabled(self):
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_VERIFICATION_ENABLED = False
            assert get_trust_verifier() is None

    def test_allowlist_when_enabled(self):
        with patch("application.security.mcp_trust.settings") as mock_settings:
            mock_settings.MCP_TRUST_VERIFICATION_ENABLED = True
            mock_settings.MCP_TRUST_ALLOWED_SERVERS = "a.com"
            mock_settings.MCP_TRUST_BLOCKED_SERVERS = None
            verifier = get_trust_verifier()
        assert isinstance(verifier, AllowlistTrustVerifier)


@pytest.mark.unit
class TestMcpToolTrustWiring:
    """Regression: MCPTool.execute_action must call the trust gate pre-flight."""

    def test_execute_action_source_enforces_trust(self):
        from pathlib import Path

        src = Path("application/agents/tools/mcp_tool.py").read_text(encoding="utf-8")
        assert "from application.security.mcp_trust import" in src
        assert "enforce_mcp_trust" in src
        assert "TrustContext" in src
        # Gate must sit inside execute_action, before call_tool.
        execute_idx = src.index("def execute_action")
        call_tool_idx = src.index('"call_tool"', execute_idx)
        enforce_idx = src.index("enforce_mcp_trust", execute_idx)
        assert execute_idx < enforce_idx < call_tool_idx
