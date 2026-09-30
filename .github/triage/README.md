# Issue and pull request triage

A DocsGPT agent on DocsGPT Cloud triages issues and pull requests on this
repository. It acts on GitHub as `arc53-machine` and reports each decision to a
maintainer on Telegram.

## How it works

```
GitHub event ──► .github/workflows/triage.yml ──► relay.py ──► agent webhook ──► DocsGPT Triage
                  (filters, skips bots and          collects facts,             labels, assigns,
                   maintainers)                     posts compact JSON          comments, Telegram
DocsGPT schedule (daily, 07:00 UTC) ──► {"kind": "stale_sweep"} ──────────────────────┘
```

- **`relay.py`** turns an event into facts the agent would otherwise have to
  dig for: the author's history here, similar issues and open PRs, who claimed
  an issue and when, CI state (including fork runs waiting for approval),
  unresolved CodeRabbit threads, new dependencies and settings, missing
  locales, whether a UI change has a screenshot, and the bot's last review of
  the PR. Standard library only; tests in `tests/scripts/test_triage_relay.py`.
- **`agent.yaml`** is the agent: its prompt (the triage rules), model, tools
  and sources. `.github/workflows/triage-agent.yml` applies it with
  `docsgpt-cli agents apply` on every push to `main` that changes it, and
  re-uploads `AGENTS.md`, `CONTRIBUTING.md`, `frontend/DESIGN.md` and
  `docs/content/` as the agent's sources when they change.
- The **triage manual** is a wiki source on DocsGPT Cloud
  (`docsgpt-triage-manual`): maintainers, label meanings, product scope and
  `/corrections.md`. Edit it in the DocsGPT UI; no deploy needed.

| Event | Kind | What the agent does |
| --- | --- | --- |
| Issue opened or reopened | `issue_opened` | Scores usefulness, clarity and spam; labels; asks for missing details, links a duplicate, or redirects a vulnerability report to private reporting; closes spam at 0.95+ |
| Comment asking to work on an issue | `issue_claim` | Assigns the first person who asks; reassigns when the current assignment is stale; declines when someone already has a PR or the claimant is over-committed |
| Issue author replies to `needs-info` | `issue_author_reply` | Removes `needs-info` when answered |
| PR opened or ready | `pr_opened` | Quick pass: `needs-screenshot`, `heavy-dependency`, competing PRs, spam |
| CodeRabbit or CI finished | `pr_review` | Verdict `ready`, `changes_needed`, `not_a_fit` or `spam`; one checklist comment per new commit; `waiting-on-author` / `maintainer-review` |
| Daily schedule | `stale_sweep` | `stale` after 14 idle days waiting on the author, closes 30 days later, frees assignments idle for 30 days |

Maintainers' own issues, comments and PRs, and bots, are skipped.

## Setup

1. **GitHub tool.** A DocsGPT MCP tool named `arc53-machine-triage` pointed at
   `https://api.githubcopilot.com/mcp/`, signed in as `arc53-machine` (repo role
   Triage; token permissions Issues and Pull requests read/write, Contents and
   Metadata read). Give it the static headers `Mcp-Param-owner: arc53` and
   `Mcp-Param-repo: DocsGPT`: GitHub's server requires them for repository
   tools, and they also pin the bot to this repository. Leave only these
   actions on: `get_me`, `issue_read`, `list_issues`, `list_pull_requests`,
   `pull_request_read`, `search_issues`, `search_pull_requests`,
   `get_file_contents`, `get_label`, `get_commit`, `list_commits`,
   `search_code`, and for live mode `issue_write`, `add_issue_comment`,
   `update_pull_request`, `update_issue_comment`.
2. **Telegram tool** named `PikaMail`, with the chat id fixed.
3. **Agent.** Run the *Triage agent* workflow (or `docsgpt-cli agents apply -f
   .github/triage/agent.yaml`), then publish the agent once in the UI. A draft
   agent has no API key, and without one DocsGPT runs it with the owner's
   chat tools instead of its own.
4. **Schedule.** On the agent's Schedules tab: daily, instruction
   `{"kind": "stale_sweep", "mode": "shadow"}`.
5. **Repository settings** (Settings → Secrets and variables → Actions):

   | Name | Kind | Value |
   | --- | --- | --- |
   | `TRIAGE_WEBHOOK_URL` | secret | The agent's webhook URL (agent → More actions → Access Details) |
   | `DOCSGPT_TRIAGE_PAT` | secret | A DocsGPT personal access token with `agents:read`, `agents:write`, `prompts:read`, `prompts:write`, `sources:read`, `sources:write`, `tools:read`, `models:read` |
   | `TRIAGE_MODE` | variable | `shadow` to start; both workflows stay off while it is unset |
   | `TRIAGE_BOT_LOGIN` | variable | Optional, defaults to `arc53-machine` |

## Modes

- **`shadow`**: the agent writes nothing to GitHub. Each Telegram report lists
  what it would have done and the comment it would have posted.
- **`live`**: set `TRIAGE_MODE=live`, switch on the four write actions of the
  GitHub tool, and change the schedule's instruction to `"mode": "live"`.

## Running it by hand

- Actions → *Triage* → *Run workflow* with an issue or PR number. A manual run
  always reports to Telegram.
- Locally, to see the facts without sending anything:
  `GITHUB_TOKEN=$(gh auth token) python .github/triage/relay.py --pr 2838 --print`

## Correcting it

When the bot gets something wrong, add an entry to `/corrections.md` in the
`docsgpt-triage-manual` wiki (date, item, what it did, what it should have
done, the rule from now on). Rules that should always hold belong in the
prompt in `agent.yaml`.
