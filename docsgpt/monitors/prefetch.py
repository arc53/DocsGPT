"""Telling a real GET on a trigger link from a link preview, a prefetch or a mail scanner.

A GET trigger link fires on any GET, so everything that opens a URL without
a person or program meaning to call it must be ignored: chat apps and social
sites unfurl links they see, mail gateways open every link in a message to
scan it, browsers prefetch, and HEAD requests only ask whether the URL
exists. :func:`ignore_reason` names why a request is one of those, and the
trigger route answers it ``200`` without counting a hit or running a check.

The lists are kept here, in one place, and matched case-insensitively as
substrings of the User-Agent, so an entry must be specific enough never to
match a real caller (``line/`` would match ``Pipeline/1.0``). Add a fetcher
when one shows up firing links; ``tests/monitors/test_prefetch.py`` holds
sample User-Agents, and ones that must never match.
This is a best-effort filter, which is why GET links are opt-in and meant only
for machine callers that can't POST.
"""

from __future__ import annotations

from typing import Mapping, Optional, Tuple

#: Link-preview, unfurl, crawler and mail-scanner User-Agents (lowercase substrings).
PREVIEW_AGENTS: Tuple[str, ...] = (
    # Chat apps
    "slackbot",  # Slackbot-LinkExpanding, Slack-ImgProxy
    "slack-imgproxy",
    "discordbot",
    "telegrambot",
    "whatsapp",
    "skypeuripreview",  # Skype and Microsoft Teams
    "microsoftpreview",
    "viber",
    "kakaotalk-scrap",
    "mattermost-bot",
    "rocket.chat",
    "synapse (bot",  # Matrix homeservers' URL previews
    "snap url preview",
    # Social sites
    "twitterbot",
    "facebookexternalhit",
    "facebot",
    "meta-externalagent",
    "linkedinbot",
    "pinterest",
    "redditbot",
    "tumblr",
    "mastodon",
    "bluesky",
    "cardyb",  # Bluesky's card fetcher
    "vkshare",
    "embedly",
    "iframely",
    "quora link preview",
    # Mail clients and link scanners
    "microsoft office",  # Office and Outlook previews
    "ms-office",
    "microsoft outlook",
    "outlook-",
    "safelinks",
    "bingpreview",
    "yahoo link preview",
    "google-safety",
    "googleimageproxy",
    "proofpoint",
    "mimecast",
    "barracuda",
    "symantec",
    # Search engines and crawlers
    "googlebot",
    "google-inspectiontool",
    "google-pagerenderer",
    "googleother",
    "google-read-aloud",
    "apis-google",
    "adsbot-google",
    "feedfetcher-google",
    "bingbot",
    "applebot",
    "duckduckbot",
    "yandexbot",
    "baiduspider",
    "petalbot",
    "bytespider",
    "semrushbot",
    "ahrefsbot",
    "gptbot",
    "chatgpt-user",
    "oai-searchbot",
    "claudebot",
    "claude-user",
    "perplexitybot",
    "amazonbot",
    "ccbot",
)

#: Request headers browsers and proxies send on a speculative fetch, and the values that mark one.
PREFETCH_HEADERS: Tuple[Tuple[str, str], ...] = (
    ("purpose", "prefetch"),
    ("sec-purpose", "prefetch"),  # also "prefetch;prerender"
    ("x-purpose", "preview"),
    ("x-purpose", "prefetch"),
    ("x-moz", "prefetch"),
)


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return str(value or "")
    return ""


def ignore_reason(method: str, headers: Mapping[str, str]) -> Optional[str]:
    """Why a request on a GET trigger link is not a real call, or None when it is.

    Args:
        method: The HTTP method.
        headers: The request headers.

    Returns:
        ``head``, ``prefetch`` (a speculative fetch header) or ``preview`` (a
        known link-preview, crawler or scanner User-Agent); None otherwise.
    """
    if str(method or "").upper() == "HEAD":
        return "head"
    for name, marker in PREFETCH_HEADERS:
        if marker in _header(headers, name).lower():
            return "prefetch"
    agent = _header(headers, "User-Agent").lower()
    if agent and any(fragment in agent for fragment in PREVIEW_AGENTS):
        return "preview"
    return None
