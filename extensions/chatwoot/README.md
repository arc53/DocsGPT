# DocsGPT Chatwoot bridge

A small Flask app that answers incoming [Chatwoot](https://www.chatwoot.com/) messages with a DocsGPT agent.
Chatwoot sends a signed `message_created` webhook to `POST /docsgpt`; the bridge asks the agent through
`/api/answer` and posts the answer back into the conversation.

Full guide: <https://docs.docsgpt.cloud/Extensions/Chatwoot-extension>

## Setup

1. Create and publish an agent in DocsGPT, then copy its API key from the agent's **Access Details**
   ([how](https://docs.docsgpt.cloud/API/agent-keys)).
2. In Chatwoot, copy the **Access Token** from your profile settings.
3. In Chatwoot, go to **Settings → Integrations → Webhooks → Configure → Add new webhook**. Set the URL to
   `http://<bridge-host>:5000/docsgpt`, subscribe to **Message created**, save, and copy the webhook's secret.
4. Configure and run the bridge:

   ```bash
   cd extensions/chatwoot
   pip install flask requests python-dotenv
   cp .env_sample .env   # then fill in the values
   flask --app app run --host 0.0.0.0 --port 5000
   ```

   `python app.py` works too; it listens on port 5000, or on `PORT` if you set it.

## Upgrading from 0.21.0 or earlier

- `python app.py` used to listen on port 80. It now listens on 5000 (or `PORT`), so update the webhook URL in
  Chatwoot or set `PORT=80`.
- `.env` is now read from this folder, next to `app.py`, instead of the directory the bridge was started from.
  Move the file here if you kept it elsewhere.

## Configuration (`.env`)

| Variable | Description |
| --- | --- |
| `docsgpt_url` | DocsGPT API base URL, e.g. `http://localhost:7091` or `https://gptcloud.arc53.com`. |
| `docsgpt_key` | API key of a published DocsGPT agent. Not an LLM provider key. |
| `chatwoot_url` | Chatwoot base URL, e.g. `https://app.chatwoot.com`. |
| `chatwoot_token` | Chatwoot profile Access Token, used to post replies. |
| `chatwoot_webhook_secret` | Secret of the Chatwoot webhook. Requests without a valid signature get `401`. |
| `chatwoot_allow_unsigned` | Optional, **insecure**. `true` accepts webhooks without a signature, for Chatwoot versions that do not sign them. See below. |
| `account_id` | Optional. Answer only in this Chatwoot account. |
| `assignee_id` | Optional. Answer only conversations assigned to this Chatwoot agent. |

Add the label `human-requested` to a conversation to stop the bot from replying in it.

The bridge verifies the `X-Chatwoot-Signature` and `X-Chatwoot-Timestamp` headers and rejects deliveries signed more
than five minutes ago, so keep the bridge host's clock in sync. If DocsGPT or Chatwoot returns an error, the bridge
logs it and answers the webhook with `502`.

### Older Chatwoot versions (unsigned webhooks)

Chatwoot versions that do not sign webhooks send neither header, so every request gets `401`. Setting
`chatwoot_allow_unsigned=true` accepts requests that carry neither header; a request that does carry them is still
verified. This is **insecure**: anyone who can reach `/docsgpt` can make the bridge query your agent and post into
your Chatwoot conversations. The bridge logs a warning at startup while it is on. Use it only when you cannot
upgrade Chatwoot, and keep the bridge reachable only from Chatwoot (a private network or an IP allowlist).
