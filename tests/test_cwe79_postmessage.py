"""
Test for CWE-79: Reflected XSS via postMessage with wildcard targetOrigin.

The callback-status page should NOT use '*' as the targetOrigin in postMessage,
because that allows any window (including an attacker's page) to receive the
session_token sent via postMessage.

The fix restricts the targetOrigin to the application's own origin.
"""

import re


ROUTES_PATH = (
    "application/api/connector/routes.py"
)
SETTINGS_PATH = (
    "application/core/settings.py"
)


def read_file(relpath):
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, relpath)) as f:
        return f.read()


def test_no_wildcard_target_origin_in_postmessage():
    """postMessage must not use '*' as targetOrigin."""
    content = read_file(ROUTES_PATH)

    # Find all postMessage calls with wildcard targetOrigin (multiline)
    wildcard_pattern = re.compile(
        r"postMessage\s*\([^)]*,\s*['\"]?\*['\"]?\s*\)", re.DOTALL
    )
    matches = wildcard_pattern.findall(content)
    assert len(matches) == 0, (
        f"Found postMessage with wildcard '*' targetOrigin: {matches}. "
        "This allows any opener window (including attacker-controlled pages) "
        "to receive sensitive data like session_token."
    )


def test_postmessage_uses_explicit_origin():
    """postMessage should use an explicit, non-wildcard targetOrigin."""
    content = read_file(ROUTES_PATH)

    assert "postMessage" in content, "Expected postMessage call in callback-status page"

    # Extract all postMessage second arguments (multiline)
    pm_pattern = re.compile(
        r"postMessage\s*\(\s*\{.*?\}\s*,\s*([^)]+)\)", re.DOTALL
    )
    matches = pm_pattern.findall(content)
    assert len(matches) > 0, "Could not find postMessage with targetOrigin argument"

    for target_origin in matches:
        stripped = target_origin.strip().strip("'\"")
        assert stripped != "*", (
            f"targetOrigin is wildcard '*'. Must be a specific origin."
        )


def test_frontend_origin_setting_exists():
    """The settings should include a FRONTEND_URL for restricting postMessage."""
    settings_content = read_file(SETTINGS_PATH)

    assert "FRONTEND_URL" in settings_content, (
        "Settings should define FRONTEND_URL to restrict postMessage targetOrigin"
    )
