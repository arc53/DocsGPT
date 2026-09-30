"""Chatwoot webhook bridge: answers incoming Chatwoot messages with a DocsGPT agent."""

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import dotenv
import requests
from flask import Flask, request

dotenv.load_dotenv(Path(__file__).with_name(".env"))
docsgpt_url = os.getenv("docsgpt_url", "").rstrip("/")
chatwoot_url = os.getenv("chatwoot_url", "").rstrip("/")
docsgpt_key = os.getenv("docsgpt_key")
chatwoot_token = os.getenv("chatwoot_token")
chatwoot_webhook_secret = os.getenv("chatwoot_webhook_secret", "")
# Optional filters: when set, only answer conversations in this account / assigned to this agent.
account_id = os.getenv("account_id") or None
assignee_id = os.getenv("assignee_id") or None
label_stop = "human-requested"
# Reject webhook deliveries signed more than this many seconds ago (replay protection).
SIGNATURE_MAX_AGE_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 120

logger = logging.getLogger(__name__)


def send_to_bot(sender: Any, message: str) -> str | None:
    """Ask the DocsGPT agent a question through ``/api/answer``.

    Args:
        sender: The Chatwoot contact id (kept for logging).
        message: The customer's message text.

    Returns:
        The agent's answer, or ``None`` if DocsGPT could not be reached or returned an error.
    """
    data = {
        'question': message,
        'api_key': docsgpt_key,
        'history': json.dumps([]),
    }
    headers = {"Content-Type": "application/json",
               "Accept": "application/json"}

    try:
        r = requests.post(f'{docsgpt_url}/api/answer',
                          json=data, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("DocsGPT request for contact %s failed: %s", sender, exc)
        return None
    if not r.ok:
        logger.error("DocsGPT returned HTTP %s for contact %s: %s", r.status_code, sender, r.text[:500])
        return None
    try:
        answer = r.json().get('answer')
    except ValueError:
        answer = None
    if not answer:
        logger.error("DocsGPT response for contact %s has no answer: %s", sender, r.text[:500])
        return None
    return answer


def send_to_chatwoot(account: Any, conversation: Any, message: str) -> dict | None:
    """Post a reply into a Chatwoot conversation.

    Args:
        account: The Chatwoot account id.
        conversation: The Chatwoot conversation id.
        message: The reply text.

    Returns:
        The created Chatwoot message, or ``None`` if Chatwoot could not be reached or rejected it.
    """
    data = {
        'content': message
    }
    url = f"{chatwoot_url}/api/v1/accounts/{account}/conversations/{conversation}/messages"
    headers = {"Content-Type": "application/json",
               "Accept": "application/json",
               "api_access_token": f"{chatwoot_token}"}

    try:
        r = requests.post(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        logger.error("Chatwoot request for conversation %s failed: %s", conversation, exc)
        return None
    if not r.ok:
        logger.error("Chatwoot returned HTTP %s for conversation %s: %s", r.status_code, conversation, r.text[:500])
        return None
    try:
        return r.json()
    except ValueError:
        return {}


def is_valid_chatwoot_signature(
    raw_body: bytes, signature_header: str | None, timestamp_header: str | None
) -> bool:
    """Validate a Chatwoot webhook signature.

    Chatwoot signs each delivery with ``sha256=HMAC-SHA256(secret, "{timestamp}.{raw_body}")`` and sends the
    timestamp in ``X-Chatwoot-Timestamp``.

    Args:
        raw_body: The unparsed request body.
        signature_header: The ``X-Chatwoot-Signature`` header value.
        timestamp_header: The ``X-Chatwoot-Timestamp`` header value (Unix seconds).

    Returns:
        True if the signature matches and the timestamp is recent.
    """
    if not chatwoot_webhook_secret or not signature_header or not timestamp_header:
        return False
    try:
        timestamp = int(timestamp_header.strip())
    except ValueError:
        return False
    if abs(time.time() - timestamp) > SIGNATURE_MAX_AGE_SECONDS:
        return False

    expected = hmac.new(
        chatwoot_webhook_secret.encode("utf-8"), f"{timestamp_header.strip()}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()

    provided = signature_header.strip()
    if provided.startswith("sha256="):
        provided = provided.split("=", maxsplit=1)[1]

    return hmac.compare_digest(provided, expected)


app = Flask(__name__)


@app.route('/docsgpt', methods=['POST'])
def docsgpt():
    """Handle a Chatwoot ``message_created`` webhook and reply with the agent's answer."""
    raw_body = request.get_data()
    signature = request.headers.get("X-Chatwoot-Signature")
    timestamp = request.headers.get("X-Chatwoot-Timestamp")
    if not is_valid_chatwoot_signature(raw_body, signature, timestamp):
        return "Unauthorized", 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return "Invalid payload", 400

    message_type = data.get('message_type')
    if message_type is None:
        return "Not a message"
    if message_type != "incoming":
        return "Not an incoming message"

    message = data.get('content')
    conversation_data = data.get('conversation') or {}
    conversation = conversation_data.get('id')
    contact = (data.get('sender') or {}).get('id')
    account = (data.get('account') or {}).get('id')
    assignee = ((conversation_data.get('meta') or {}).get('assignee') or {}).get('id')
    if not message or conversation is None or account is None:
        return "Nothing to answer"

    if label_stop in (conversation_data.get('labels') or []):
        return "Label stop"
    if account_id and str(account) != str(account_id):
        return "Not the right account"
    if assignee_id and str(assignee) != str(assignee_id):
        return "Not the right assignee"

    bot_response = send_to_bot(contact, message)
    if bot_response is None:
        return "DocsGPT request failed", 502
    create_message = send_to_chatwoot(account, conversation, bot_response)
    if create_message is None:
        return "Chatwoot request failed", 502
    return create_message


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", "5000")))
