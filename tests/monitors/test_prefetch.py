"""The link-preview and prefetch filter for GET trigger links: what it ignores, and what it must never ignore."""

from __future__ import annotations

import pytest

from docsgpt.monitors.prefetch import PREVIEW_AGENTS, ignore_reason

#: Real User-Agents of fetchers that open links nobody meant to call.
PREVIEWS = [
    "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "Slackbot 1.0 (+https://api.slack.com/robots)",
    "Slack-ImgProxy (+https://api.slack.com/robots)",
    "Twitterbot/1.0",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
    "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "TelegramBot (like TwitterBot)",
    "WhatsApp/2.23.20.0 A",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) SkypeUriPreview Preview/0.5",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 "
    + "Safari/537.36 Microsoft Office/16.0 (Windows NT 10.0; Microsoft Outlook 16.0.17126; Pro)",
    "Microsoft Office Existence Discovery",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Google-InspectionTool/1.0)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 "
    + "Safari/605.1.15 (Applebot/0.1; +http://www.apple.com/go/applebot)",
    "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; BingPreview/1.0b)",
    "Mozilla/5.0 (compatible; redditbot/1.0; +http://www.reddit.com/feedback)",
    "Mozilla/5.0 (compatible; Embedly/0.2; +http://support.embed.ly/)",
    "Iframely/1.3.1 (+https://iframely.com/docs/about)",
    "http.rb/5.1.1 (Mastodon/4.2.1; +https://mastodon.social/)",
    "Bluesky Cardyb/1.1",
    "Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ChatGPT-User/1.0; +https://openai.com/bot)",
    "Synapse (bot; +https://github.com/matrix-org/synapse)",
    "mattermost-bot/4.1",
]

#: Callers a GET link exists for: none may ever be ignored.
CALLERS = [
    "curl/8.5.0",
    "Wget/1.21.4",
    "python-requests/2.32.3",
    "python-httpx/0.27.0",
    "Go-http-client/2.0",
    "okhttp/4.12.0",
    "axios/1.7.2",
    "node-fetch/1.0 (+https://github.com/bitinn/node-fetch)",
    "Mozilla/5.0 (Windows NT; Windows NT 10.0; en-US) WindowsPowerShell/5.1.19041.4648",
    "Zapier",
    "IFTTT-Protocol/v1",
    "n8n",
    "HomeAssistant/2024.6.0 aiohttp/3.9.5 Python/3.12",
    "Shortcuts/2302.0.4 CFNetwork/1410.0.3 Darwin/22.6.0",
    "Pipeline/1.0",
    "GitLab/16.11.0",
    "Jenkins/2.452",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "",
]


@pytest.mark.parametrize("agent", PREVIEWS)
def test_link_previews_are_ignored(agent):
    assert ignore_reason("GET", {"User-Agent": agent}) == "preview"


@pytest.mark.parametrize("agent", CALLERS)
def test_real_callers_are_never_ignored(agent):
    assert ignore_reason("GET", {"User-Agent": agent}) is None


@pytest.mark.parametrize(
    "headers",
    [
        {"Purpose": "prefetch"},
        {"Sec-Purpose": "prefetch"},
        {"sec-purpose": "prefetch;prerender"},
        {"X-Purpose": "preview"},
        {"X-Moz": "prefetch"},
    ],
)
def test_prefetches_are_ignored(headers):
    assert ignore_reason("GET", {"User-Agent": "Mozilla/5.0", **headers}) == "prefetch"


def test_head_is_ignored():
    assert ignore_reason("HEAD", {"User-Agent": "curl/8.5.0"}) == "head"


def test_the_list_is_lowercase_and_unique():
    assert all(entry == entry.lower() and entry.strip() == entry and entry for entry in PREVIEW_AGENTS)
    assert len(set(PREVIEW_AGENTS)) == len(PREVIEW_AGENTS)
