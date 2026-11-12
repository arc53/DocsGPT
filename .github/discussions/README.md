# Discussions answers

A DocsGPT agent on DocsGPT Cloud answers questions in this repository's
Discussions from the product docs and the code, and reports each run to a
maintainer on Telegram.

## How it works

```
discussion created ─┐
author replies to   ├─► discussions.yml ─► answer.py ─► /v1/chat/completions ─► DocsGPT Discussions
the bot's answer   ─┘                     facts, rules    (agent API key)        docs search, GitHub
                                          ◄── {"decision", "confidence", "answer", "reason"} ──┘ (read-only), Telegram
                                          live mode: checks the answer, then posts it
```

- **`answer.py`** decides whether a discussion should be answered, sends the
  agent the discussion and its comments, and in live mode posts the answer with
  the workflow's `GITHUB_TOKEN` (so it appears as `github-actions`). Standard
  library only; tests in `tests/scripts/test_discussions_answer.py`.
- **`agent.yaml`** is the agent: its prompt, model, tools and sources. It reuses
  the `docsgpt-product-docs` and `docsgpt-contributor-guides` sources that
  `.github/workflows/triage-agent.yml` keeps current. CI does not apply it; run
  `docsgpt-cli agents apply -f .github/discussions/agent.yaml` after changing it.

What gets answered:

- New discussions in the categories in `DISCUSSIONS_CATEGORIES` (default
  `q-a,general`), unless a maintainer or a bot opened them. The agent itself
  skips ideas, show-and-tell and chat, and escalates bugs, security reports and
  anything its sources don't settle.
- The author's replies inside the bot's thread, up to 2 follow-ups per thread.
- Nothing once the discussion is answered, locked or closed, or a maintainer has
  commented anywhere in it.

Before posting, `answer.py` holds back an answer that links outside
`docsgpt.cloud`, `docs.ac`, `github.com/arc53/` and `localhost` (for examples),
mentions anyone but the author, or runs past 6000 characters; the run then
fails so it shows up in Actions. Each request carries an `Idempotency-Key`, so re-running a run returns
the earlier answer instead of running the agent again.

## Setup

1. **GitHub tool.** A DocsGPT MCP tool named `docsgpt-github-readonly` pointed at
   `https://api.githubcopilot.com/mcp/readonly`, signed in with a token that can
   read this repository, with the static headers `Mcp-Param-owner: arc53` and
   `Mcp-Param-repo: DocsGPT`. Leave on `get_file_contents`, `search_code`,
   `search_issues`, `issue_read`, `list_issues` and `search_pull_requests`.
2. **Telegram tool** named `PikaMail`, with the chat id fixed (the same one the
   triage agent uses).
3. **Agent.** `docsgpt-cli agents apply -f .github/discussions/agent.yaml`, then
   publish it in the UI and copy its API key.
4. **Repository settings** (Settings → Secrets and variables → Actions):

   | Name | Kind | Value |
   | --- | --- | --- |
   | `DOCSGPT_DISCUSSIONS_AGENT_KEY` | secret | The agent's API key |
   | `DISCUSSIONS_MODE` | variable | `shadow` to start; the workflow stays off while it is unset |
   | `DISCUSSIONS_CATEGORIES` | variable | Optional, comma-separated category slugs; default `q-a,general` |
   | `DISCUSSIONS_MAINTAINERS` | variable | Optional, comma-separated logins; default the list in `answer.py` |

## Modes

- **`shadow`**: nothing is posted. The Telegram report carries the answer the
  agent would have posted.
- **`live`**: set `DISCUSSIONS_MODE=live`; answers are posted.

## Running it by hand

- Actions → *Discussions* → *Run workflow* with a discussion number, or with the
  number empty to work through the open, unanswered backlog (`limit`,
  `max_age_days`).
- Locally, to see what the agent would get without sending anything:
  `GITHUB_TOKEN=$(gh auth token) python .github/discussions/answer.py --number 1457 --dry-run`
