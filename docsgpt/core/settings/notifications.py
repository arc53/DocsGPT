"""Notifications: Web Push to browsers with no DocsGPT tab open."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import Field
from pydantic_settings import NoDecode

from docsgpt.core.settings._shared import EnvList, SettingsGroup


class NotificationSettings(SettingsGroup):
    """The VAPID key pair Web Push is signed with, and which push services may be sent to."""

    WEBPUSH_VAPID_PUBLIC_KEY: Optional[str] = Field(
        default=None,
        description=(
            "VAPID public key for Web Push, raw base64url (the uncompressed P-256 point, as `npx web-push "
            "generate-vapid-keys` prints it). Browsers subscribe with it. Derived from the private key when unset; "
            "when both are set they must belong together."
        ),
    )
    WEBPUSH_VAPID_PRIVATE_KEY: Optional[str] = Field(
        default=None,
        description=(
            "VAPID private key for Web Push, raw base64url. Unset, Web Push is off: users with no tab open get "
            "only the unread mark. Changing the key pair invalidates every browser's subscription; browsers "
            "subscribe again on their next visit."
        ),
    )
    WEBPUSH_VAPID_SUBJECT: Optional[str] = Field(
        default=None,
        description=(
            "Contact the push services can reach the operator at: a `mailto:` or `https:` URL. Apple rejects "
            "pushes without a real one. Unset, the public API URL is used when it is https."
        ),
    )
    WEBPUSH_EXTRA_ALLOWED_HOSTS: Annotated[list[str], NoDecode, EnvList()] = Field(
        default_factory=list,
        description=(
            "Push service hosts to accept besides the known ones (Google FCM, Mozilla, Apple, Windows), as a "
            "comma list or JSON list. `*.example.com` matches subdomains. Subscription endpoints must be https on "
            "an allowed host, so the server never posts to an arbitrary URL; this is for self-hosted push services "
            "and tests."
        ),
    )
