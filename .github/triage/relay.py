#!/usr/bin/env python3
"""Relay GitHub events to the DocsGPT triage agent.

Collects facts about an issue or pull request from the GitHub API and writes a
compact JSON payload for the agent, so it spends its tokens on judgement instead
of on raw event payloads. ``docsgpt-cli agents trigger`` then posts each payload
to the agent's webhook (see .github/workflows/triage.yml). Standard library only.

    python .github/triage/relay.py --out DIR       # from a GitHub Actions event
    python .github/triage/relay.py --issue 2836    # one issue, printed
    python .github/triage/relay.py --pr 2838 --out DIR
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

API = "https://api.github.com"
DEFAULT_REPO = "arc53/DocsGPT"
DEFAULT_BOT = "arc53-machine"
DEFAULT_SKIP_ASSOCIATIONS = "OWNER,MEMBER,COLLABORATOR"
# Org membership is often private, and GitHub then reports a maintainer as CONTRIBUTOR.
DEFAULT_MAINTAINERS = "dartpain,pabik,ManishMadan2882,siiddhantt,tenokami,arc53-machine"
# Events a bot legitimately sends: CodeRabbit's status, and CI runs started for a bot's push.
BOT_SENT_EVENTS = frozenset({"status", "workflow_run"})
LOCALES = ("de", "en", "es", "jp", "ru", "zh", "zh-TW")
MARKER = "docsgpt-triage"

BODY_LIMIT = 6000
COMMENT_LIMIT = 400
PATCH_LIMIT = 1500
DIFF_LIMIT = 14000
FILES_LIMIT = 60

CLAIM_RE = re.compile(
    r"\b("
    r"(can|could|may) i (please )?(work on|take|pick|fix|handle|tackle|try|contribute)"
    r"|i('d| would| want to| wanna| will|'ll| can| am going to|'m going to)( like to| love to)?"
    r" (work on|take|pick up|fix|handle|tackle|give it a (try|shot)|contribute)"
    r"|(please |pls |kindly )?assign( (this|it|the issue))?( to)? me"
    r"|i('m| am) (already )?working on (this|it)"
    r"|let me (take|work on|fix|handle)"
    r")\b",
    re.IGNORECASE,
)
MEDIA_RE = re.compile(
    r"(!\[[^\]]*\]\([^)]+\)|<img\s|<video\s|user-attachments/assets/|"
    r"\.(png|jpe?g|gif|webp|mp4|mov|webm)\b)",
    re.IGNORECASE,
)
LINKED_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|related to|part of)\s*:?\s*"
    r"(?:https://github\.com/[\w.-]+/[\w.-]+/issues/|#)(\d+)",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://([^/\s)>\]]+)", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
DETAILS_RE = re.compile(r"<details>.*?</details>", re.DOTALL | re.IGNORECASE)
MARKER_RE = re.compile(r"<!--\s*" + MARKER + r"\s+([^>]*?)\s*-->")
TITLE_PREFIX_RE = re.compile(
    r"^\s*(\[[^\]]*\]\s*)*([^\w\s]\s*)*(bug report|feature( request)?|proposal|report|bug)\s*:?\s*",
    re.IGNORECASE,
)
SETTING_RE = re.compile(r"^\+\s+([A-Z][A-Z0-9_]{2,})\s*:")
SEVERITY_RE = re.compile(r"\b(Critical|Major|Minor|Trivial|Nitpick)\b")
STOPWORDS = frozenset(
    """a an and are as at be but by can could do does for from has have how i if in into is it its
    not of on or should so that the their then there this to too use using via was we when where
    which while will with without you your add adds added support supports fix fixes new make
    allow allows option optional feature bug report issue error docsgpt""".split()
)

PY_DEP_RE = re.compile(r'^([+-])\s*"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*([<>=!~][^";]*)')
JS_DEP_RE = re.compile(r'^([+-])\s*"(@?[a-z0-9][\w.-]*(?:/[\w.-]+)?)"\s*:\s*"([^"]+)"')
JS_VERSION_RE = re.compile(r"^(\^|~|>=?|<=?|=|\d|\*|latest|next|workspace:|npm:|file:|link:|git|github:|https?:)")
JS_NON_DEP_KEYS = frozenset(
    "name version description main module types type license author homepage private packageManager".split()
)


def now_utc() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def parse_time(value: Optional[str]) -> Optional[datetime]:
    """Parse a GitHub ISO timestamp."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def days_since(value: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    """Whole days between a GitHub timestamp and now."""
    moment = parse_time(value)
    if moment is None:
        return None
    return ((now or now_utc()) - moment).days


def truncate(text: Optional[str], limit: int) -> str:
    """Trim text to ``limit`` characters, marking the cut."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n…[truncated, {len(text) - limit} more chars]"


def clean_bot_text(text: Optional[str]) -> str:
    """Drop HTML comments and collapsed blocks from a bot-written comment."""
    return DETAILS_RE.sub("", HTML_COMMENT_RE.sub("", text or "")).strip()


def is_claim(text: Optional[str]) -> bool:
    """True when a comment asks to work on, or be assigned to, the issue."""
    return bool(CLAIM_RE.search(text or ""))


def has_media(text: Optional[str]) -> bool:
    """True when markdown/HTML embeds an image, GIF or video."""
    return bool(MEDIA_RE.search(text or ""))


def linked_issues(text: Optional[str]) -> list[int]:
    """Issue numbers a PR body says it fixes or relates to."""
    seen: list[int] = []
    for match in LINKED_RE.finditer(text or ""):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def link_domains(text: Optional[str]) -> list[str]:
    """Distinct link domains in a body, GitHub's own excluded."""
    domains: list[str] = []
    for match in URL_RE.finditer(text or ""):
        host = match.group(1).lower().split(":")[0]
        if host.endswith(("github.com", "githubusercontent.com")) or host in domains:
            continue
        domains.append(host)
    return domains


def title_keywords(title: str) -> list[str]:
    """Search keywords from an issue title, template prefix and stopwords removed."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}", TITLE_PREFIX_RE.sub("", title))
    keywords: list[str] = []
    for word in words:
        lower = word.lower().strip(".")
        if lower not in STOPWORDS and lower not in keywords:
            keywords.append(lower)
    return keywords


def parse_marker(text: Optional[str]) -> Optional[dict[str, str]]:
    """The ``key=value`` pairs of the last triage marker in a comment."""
    matches = MARKER_RE.findall(text or "")
    if not matches:
        return None
    return dict(pair.split("=", 1) for pair in matches[-1].split() if "=" in pair)


def classify_paths(paths: list[str]) -> dict[str, Any]:
    """Areas a change touches, plus whether it changes UI and which locales."""
    areas: set[str] = set()
    locales: set[str] = set()
    ui = False
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if path.startswith("frontend/"):
            areas.add("frontend")
            if path.startswith("frontend/src/") and name.endswith((".tsx", ".css", ".jsx")):
                ui = True
            locale = re.match(r"frontend/src/locale/([\w-]+)\.json$", path)
            if locale:
                locales.add(locale.group(1))
        elif path.startswith("extensions/"):
            areas.add("extensions")
            if "/src/" in path and name.endswith((".tsx", ".css", ".jsx")):
                ui = True
        elif path.startswith(("docsgpt/", "application/")):
            areas.add("backend")
        elif path.startswith("docs/"):
            areas.add("docs")
        elif path.startswith(".github/"):
            areas.add("ci")
        elif path.startswith("deployment/"):
            areas.add("deployment")
        if path.startswith("tests/") or ".test." in name or "/__tests__/" in path:
            areas.add("tests")
        if name in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json") or name.startswith(
            "requirements"
        ):
            areas.add("dependencies")
    return {
        "areas": sorted(areas),
        "ui_changed": ui,
        "locales_touched": sorted(locales),
        "locales_missing": sorted(set(LOCALES) - locales) if locales else [],
    }


def dependency_changes(files: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """Dependencies a PR adds, removes or re-pins, read from manifest patches."""
    added: dict[tuple[str, str], str] = {}
    removed: dict[tuple[str, str], str] = {}
    for item in files:
        path = item.get("filename", "")
        name = path.rsplit("/", 1)[-1]
        if name not in ("pyproject.toml", "package.json"):
            continue
        for line in (item.get("patch") or "").splitlines():
            if name == "pyproject.toml":
                match = PY_DEP_RE.match(line)
                if not match:
                    continue
                sign, dep, spec = match.group(1), match.group(2).lower(), match.group(4).strip()
            else:
                match = JS_DEP_RE.match(line)
                if not match or match.group(2) in JS_NON_DEP_KEYS or not JS_VERSION_RE.match(match.group(3)):
                    continue
                sign, dep, spec = match.group(1), match.group(2), match.group(3)
            (added if sign == "+" else removed)[(path, dep)] = spec
    result: dict[str, list[dict[str, str]]] = {"added": [], "removed": [], "changed": []}
    for key, spec in added.items():
        if key in removed:
            if removed[key] != spec:
                result["changed"].append({"file": key[0], "name": key[1], "from": removed[key], "to": spec})
        else:
            result["added"].append({"file": key[0], "name": key[1], "spec": spec})
    for key, spec in removed.items():
        if key not in added:
            result["removed"].append({"file": key[0], "name": key[1], "spec": spec})
    return result


def new_settings(files: list[dict[str, Any]]) -> list[str]:
    """Settings (env vars) a PR adds under ``docsgpt/core/settings/``."""
    added: list[str] = []
    for item in files:
        if not item.get("filename", "").startswith("docsgpt/core/settings/"):
            continue
        for line in (item.get("patch") or "").splitlines():
            match = SETTING_RE.match(line)
            if match and match.group(1) not in added:
                added.append(match.group(1))
    return added


def ci_state(check_runs: list[dict], workflow_runs: list[dict], statuses: list[dict]) -> dict[str, Any]:
    """Summarize CI for a commit: none, awaiting_approval, pending, failure or success."""
    failed: list[str] = []
    pending: list[str] = []
    passed = 0
    awaiting = [run.get("name", "") for run in workflow_runs if run.get("conclusion") == "action_required"]
    for run in check_runs:
        if run.get("name") == "triage":
            continue
        if run.get("status") != "completed":
            pending.append(run.get("name", ""))
        elif run.get("conclusion") in ("failure", "timed_out", "cancelled", "startup_failure"):
            failed.append(run.get("name", ""))
        else:
            passed += 1
    for status in statuses:
        context = status.get("context", "")
        if context.startswith("Vercel") or context == "CodeRabbit":
            continue
        if status.get("state") == "pending":
            pending.append(context)
        elif status.get("state") in ("failure", "error"):
            failed.append(context)
        else:
            passed += 1
    if failed:
        state = "failure"
    elif pending:
        state = "pending"
    elif awaiting and not passed:
        state = "awaiting_approval"
    elif passed:
        state = "success"
    else:
        state = "none"
    return {"state": state, "failed": failed, "pending": pending, "awaiting_approval": awaiting, "passed": passed}


@dataclass(frozen=True)
class Maintainers:
    """Who maintains the repo: a listed login, or an association GitHub reports for members."""

    logins: frozenset
    associations: frozenset

    @classmethod
    def from_env(cls, logins: Optional[str], associations: Optional[str]) -> "Maintainers":
        """Build from comma-separated lists, falling back to the defaults."""
        return cls(
            frozenset(x.strip().lower() for x in (logins or DEFAULT_MAINTAINERS).split(",") if x.strip()),
            frozenset(x.strip() for x in (associations or DEFAULT_SKIP_ASSOCIATIONS).split(",") if x.strip()),
        )

    def includes(self, login: Optional[str], association: Optional[str] = None) -> bool:
        """True for a listed login or a maintainer association."""
        return (login or "").lower() in self.logins or association in self.associations


def route(event_name: str, event: dict[str, Any], bot: str, maintainers: Maintainers) -> dict[str, Any]:
    """Decide what an Actions event asks of the agent; ``kind`` is None to skip."""
    sender = event.get("sender") or {}
    if event_name not in BOT_SENT_EVENTS and (sender.get("login") == bot or sender.get("type") == "Bot"):
        return {"kind": None, "reason": f"sender {sender.get('login')} is a bot"}
    action = event.get("action")
    if event_name == "issues" and action in ("opened", "reopened"):
        issue = event["issue"]
        if (issue.get("user") or {}).get("type") == "Bot":
            return {"kind": None, "reason": "issue opened by a bot"}
        return {"kind": "issue_opened", "number": issue["number"]}
    if event_name == "issue_comment" and action == "created":
        issue, comment = event["issue"], event["comment"]
        if issue.get("pull_request") or issue.get("state") != "open":
            return {"kind": None, "reason": "comment on a pull request or a closed issue"}
        if maintainers.includes((comment.get("user") or {}).get("login"), comment.get("author_association")):
            return {"kind": None, "reason": "comment from a maintainer"}
        labels = {label["name"] for label in issue.get("labels", [])}
        by_author = (comment.get("user") or {}).get("login") == (issue.get("user") or {}).get("login")
        if is_claim(comment.get("body")):
            return {"kind": "issue_claim", "number": issue["number"], "comment_id": comment["id"]}
        if by_author and labels & {"needs-info", "waiting-on-author", "stale"}:
            return {"kind": "issue_author_reply", "number": issue["number"], "comment_id": comment["id"]}
        return {"kind": None, "reason": "comment is neither a claim nor an awaited author reply"}
    if event_name == "pull_request_target" and action in ("opened", "reopened", "ready_for_review"):
        pr = event["pull_request"]
        if pr.get("draft"):
            return {"kind": None, "reason": "draft pull request"}
        author = pr.get("user") or {}
        if author.get("type") == "Bot" or author.get("login") == bot:
            return {"kind": None, "reason": "pull request from a bot"}
        if maintainers.includes(author.get("login"), pr.get("author_association")):
            return {"kind": None, "reason": "pull request from a maintainer"}
        return {"kind": "pr_opened", "number": pr["number"]}
    if event_name == "status":
        if event.get("context") != "CodeRabbit" or event.get("state") != "success":
            return {"kind": None, "reason": "status is not a finished CodeRabbit review"}
        return {"kind": "pr_review", "sha": event["sha"]}
    if event_name == "workflow_run" and action == "completed":
        run = event["workflow_run"]
        if run.get("event") != "pull_request":
            return {"kind": None, "reason": "workflow run not from a pull request"}
        decision = {"kind": "pr_review", "sha": run["head_sha"]}
        # Listed for same-repository PRs only; fork PRs fall back to a search on the SHA.
        numbers = [pr["number"] for pr in run.get("pull_requests") or [] if pr.get("number")]
        if numbers:
            decision["numbers"] = numbers
        return decision
    return {"kind": None, "reason": f"unhandled event {event_name}.{action}"}


SECONDARY_LIMIT_WAIT = 60


def rate_limit_wait(status: int, headers: Any, body: bytes = b"", cap: int = 65) -> Optional[int]:
    """Seconds to wait before retrying a rate-limited request, or None when it wasn't one."""
    if status not in (403, 429):
        return None
    retry_after = headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), cap)
    if headers.get("X-RateLimit-Remaining") == "0" and (headers.get("X-RateLimit-Reset") or "").isdigit():
        return max(1, min(int(headers["X-RateLimit-Reset"]) - int(time.time()) + 1, cap))
    # A burst of searches trips the secondary limit, which sends neither header.
    if b"secondary rate limit" in body.lower():
        return min(SECONDARY_LIMIT_WAIT, cap)
    return None


class GitHub:
    """Minimal GitHub REST/GraphQL client."""

    def __init__(self, token: Optional[str], repo: str) -> None:
        self.token = token
        self.repo = repo
        self.owner, self.name = repo.split("/", 1)

    def _request(self, url: str, data: Optional[bytes] = None) -> Any:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        headers["User-Agent"] = "docsgpt-triage-relay"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(3):
            request = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read().decode() or "null")
            except urllib.error.HTTPError as error:
                wait = rate_limit_wait(error.code, error.headers, error.read())
                if wait is None or attempt == 2:
                    raise
                print(f"GitHub rate limit, retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError("unreachable")

    def get(self, path: str, **params: Any) -> Any:
        """GET a REST path, relative to the repo when it starts with ``/``."""
        url = f"{API}/repos/{self.repo}{path}" if path.startswith("/") else f"{API}/{path}"
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return self._request(f"{url}{query}")

    def pages(self, path: str, limit: int = 300, **params: Any) -> list:
        """GET every page of a list endpoint, up to ``limit`` items."""
        items: list = []
        page = 1
        while len(items) < limit:
            batch = self.get(path, per_page=100, page=page, **params)
            if isinstance(batch, dict):
                batch = next((value for value in batch.values() if isinstance(value, list)), [])
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items[:limit]

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search issues and pull requests in this repo."""
        return self.get("search/issues", q=f"repo:{self.repo} {query}", per_page=limit)

    def count(self, query: str) -> int:
        """Number of issues/PRs matching a repo search."""
        return int(self.search(query, limit=1).get("total_count", 0))

    def graphql(self, query: str, **variables: Any) -> Any:
        """Run a GraphQL query."""
        body = json.dumps({"query": query, "variables": variables}).encode()
        return self._request(f"{API}/graphql", data=body)


def count_or_none(gh: GitHub, query: str) -> Optional[int]:
    """A search count, or None when GitHub refuses the query or rate-limits it."""
    try:
        return gh.count(query)
    except urllib.error.HTTPError as error:
        print(f"Search refused ({error.code}): {query}", file=sys.stderr)
        return None


def search_items(gh: GitHub, query: str, limit: int) -> list[dict[str, Any]]:
    """Search results for optional facts; empty when GitHub refuses or rate-limits the search."""
    try:
        return gh.search(query, limit=limit).get("items", [])
    except urllib.error.HTTPError as error:
        print(f"Search refused ({error.code}): {query}", file=sys.stderr)
        return []


def author_facts(gh: GitHub, login: str, association: Optional[str]) -> dict[str, Any]:
    """Account age and history in this repo, for spam and experience signals."""
    user = gh.get(f"users/{login}")
    assigned = assigned_open_issues(gh, login)
    return {
        "login": login,
        "association": association,
        "type": user.get("type"),
        "account_age_days": days_since(user.get("created_at")),
        "public_repos": user.get("public_repos"),
        "followers": user.get("followers"),
        "prs_merged_here": count_or_none(gh, f"is:pr is:merged author:{login}"),
        "prs_open_here": count_or_none(gh, f"is:pr is:open author:{login}"),
        "issues_opened_here": count_or_none(gh, f"is:issue author:{login}"),
        "issues_assigned_open_here": None if assigned is None else len(assigned),
    }


CLAIM_WINDOW_MINUTES = 30


def assigned_open_issues(gh: GitHub, login: str) -> Optional[list[int]]:
    """Open issues assigned to ``login``, from the issues API (search lags behind new assignments)."""
    try:
        items = gh.pages("/issues", limit=100, assignee=login, state="open")
    except urllib.error.HTTPError as error:
        print(f"Assigned issues for {login} unavailable ({error.code})", file=sys.stderr)
        return None
    return [item["number"] for item in items if "pull_request" not in item]


def pending_claims(
    comments: list[dict[str, Any]], login: str, before: str, exclude: int, assigned: list[int]
) -> list[int]:
    """Other issues ``login`` asked to work on shortly before this claim and isn't assigned to yet.

    Claims made seconds apart are triaged in parallel, so none of them sees the
    others' assignment; counting the earlier ones keeps the per-person limit.
    """
    start = parse_time(before) - timedelta(minutes=CLAIM_WINDOW_MINUTES)
    numbers: list[int] = []
    for comment in comments:
        created = parse_time(comment.get("created_at"))
        url = comment.get("html_url") or ""
        if (comment.get("user") or {}).get("login") != login or "/issues/" not in url or not created:
            continue
        if not start <= created < parse_time(before) or not is_claim(comment.get("body")):
            continue
        number = int(url.split("/issues/")[1].split("#")[0])
        if number != exclude and number not in assigned and number not in numbers:
            numbers.append(number)
    return numbers


def comment_view(comment: dict[str, Any]) -> dict[str, Any]:
    """The parts of a comment the agent needs."""
    return {
        "id": comment["id"],
        "author": (comment.get("user") or {}).get("login"),
        "association": comment.get("author_association"),
        "created_at": comment.get("created_at"),
        "body": truncate(comment.get("body"), COMMENT_LIMIT),
    }


def similar_items(gh: GitHub, number: int, title: str, qualifier: str = "is:issue") -> list[dict[str, Any]]:
    """Likely duplicates found by searching the title's keywords."""
    keywords = title_keywords(title)[:4]
    if not keywords:
        return []
    found = search_items(gh, f"{qualifier} in:title {' '.join(keywords[:3])}", 6)
    if len(found) < 3 and len(keywords) > 1:
        found += search_items(gh, f"{qualifier} in:title {' OR '.join(keywords)}", 6)
    seen: set[int] = set()
    similar = []
    for item in found:
        if item["number"] == number or item["number"] in seen:
            continue
        seen.add(item["number"])
        similar.append(
            {
                "number": item["number"],
                "title": item["title"],
                "state": item["state"],
                "author": (item.get("user") or {}).get("login"),
                "labels": [label["name"] for label in item.get("labels", [])],
            }
        )
    return similar[:5]


def issue_facts(gh: GitHub, number: int, bot: str, maintainers: Maintainers) -> dict[str, Any]:
    """Facts about an issue: content, author, claimants, assignment and linked PRs."""
    issue = gh.get(f"/issues/{number}")
    comments = gh.pages(f"/issues/{number}/comments", limit=200)
    timeline = gh.pages(f"/issues/{number}/timeline", limit=300)
    assigned_at: dict[str, str] = {}
    unassigned: list[str] = []
    open_prs: list[dict[str, Any]] = []
    for event in timeline:
        if event.get("event") == "assigned" and event.get("assignee"):
            assigned_at[event["assignee"]["login"]] = event["created_at"]
        if event.get("event") == "unassigned" and event.get("assignee"):
            unassigned.append(event["assignee"]["login"])
        source = (event.get("source") or {}).get("issue") or {}
        if event.get("event") == "cross-referenced" and source.get("pull_request") and source.get("state") == "open":
            open_prs.append(
                {"number": source["number"], "title": source["title"], "author": source["user"]["login"]}
            )
    last_activity: dict[str, str] = {}
    for comment in comments:
        last_activity[comment["user"]["login"]] = comment["created_at"]
    claimants = [
        {"login": c["user"]["login"], "at": c["created_at"], "comment_id": c["id"]}
        for c in comments
        if not maintainers.includes(c["user"]["login"], c.get("author_association"))
        and c["user"].get("type") != "Bot"
        and c["user"]["login"] != bot
        and is_claim(c.get("body"))
    ]
    author = issue["user"]["login"]
    return {
        "number": number,
        "url": issue["html_url"],
        "title": issue["title"],
        "state": issue["state"],
        "body": truncate(issue.get("body"), BODY_LIMIT),
        "body_has_media": has_media(issue.get("body")),
        "link_domains": link_domains(issue.get("body")),
        "labels": [label["name"] for label in issue.get("labels", [])],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "author": author_facts(gh, author, issue.get("author_association")),
        "assignees": [
            {
                "login": a["login"],
                "assigned_at": assigned_at.get(a["login"]),
                "last_comment_at": last_activity.get(a["login"]),
                "has_open_pr": any(pr["author"] == a["login"] for pr in open_prs),
            }
            for a in issue.get("assignees", [])
        ],
        "claimants": claimants,
        "previously_unassigned": sorted(set(unassigned)),
        "open_prs_referencing": open_prs,
        "comment_count": issue.get("comments", 0),
        "recent_comments": [comment_view(c) for c in comments[-12:]],
        "similar_issues": similar_items(gh, number, issue["title"]),
    }


REVIEW_THREADS = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes { isResolved isOutdated path line
          comments(first: 1) { nodes { author { login } body } } }
      }
    }
  }
}
"""


def coderabbit_facts(gh: GitHub, number: int, statuses: list[dict]) -> dict[str, Any]:
    """CodeRabbit's review status and the review threads still open."""
    status = next((s for s in statuses if s.get("context") == "CodeRabbit"), None)
    result = gh.graphql(REVIEW_THREADS, owner=gh.owner, name=gh.name, number=number)
    nodes = (((result or {}).get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    threads = (nodes.get("reviewThreads") or {}).get("nodes") or []
    unresolved: list[dict[str, Any]] = []
    resolved = outdated = 0
    for thread in threads:
        first = ((thread.get("comments") or {}).get("nodes") or [{}])[0]
        if not ((first.get("author") or {}).get("login") or "").startswith("coderabbitai"):
            continue
        if thread.get("isResolved"):
            resolved += 1
        elif thread.get("isOutdated"):
            outdated += 1
        else:
            body = clean_bot_text(first.get("body"))
            severity = SEVERITY_RE.search(body)
            unresolved.append(
                {
                    "path": thread.get("path"),
                    "line": thread.get("line"),
                    "severity": severity.group(1) if severity else None,
                    "excerpt": truncate(body, 300),
                }
            )
    return {
        "status": status.get("state") if status else "absent",
        "status_description": status.get("description") if status else None,
        "threads_resolved": resolved,
        "threads_outdated_unresolved": outdated,
        "threads_unresolved": len(unresolved),
        "unresolved": unresolved[:10],
    }


def diff_excerpt(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Per-file patches, UI files first, capped so the payload stays small."""
    skip = ("package-lock.json", "uv.lock", ".svg", ".snap")
    ordered = sorted(files, key=lambda f: not f["filename"].startswith(("frontend/src/", "extensions/")))
    excerpt: list[dict[str, str]] = []
    budget = DIFF_LIMIT
    for item in ordered:
        if budget <= 0 or item["filename"].endswith(skip) or not item.get("patch"):
            continue
        patch = truncate(item["patch"], min(PATCH_LIMIT, budget))
        budget -= len(patch)
        excerpt.append({"file": item["filename"], "patch": patch})
    return excerpt


def pr_facts(gh: GitHub, number: int, bot: str) -> dict[str, Any]:
    """Facts about a PR: size, areas, dependencies, CI, CodeRabbit, reviews and history."""
    pr = gh.get(f"/pulls/{number}")
    files = gh.pages(f"/pulls/{number}/files", limit=300)
    sha = pr["head"]["sha"]
    check_runs = gh.pages(f"/commits/{sha}/check-runs", limit=200)
    workflow_runs = gh.pages("/actions/runs", limit=100, head_sha=sha)
    statuses = gh.get(f"/commits/{sha}/status").get("statuses", [])
    reviews = gh.pages(f"/pulls/{number}/reviews", limit=100)
    comments = gh.pages(f"/issues/{number}/comments", limit=200)
    latest_review: dict[str, str] = {}
    for review in reviews:
        user = review.get("user") or {}
        if user.get("type") != "Bot" and review.get("state") in ("APPROVED", "CHANGES_REQUESTED"):
            latest_review[user["login"]] = review["state"]
    last_marker = None
    for comment in comments:
        if (comment.get("user") or {}).get("login") == bot:
            marker = parse_marker(comment.get("body"))
            if marker:
                last_marker = {**marker, "comment_id": comment["id"], "at": comment["created_at"]}
    linked = []
    for issue_number in linked_issues(pr.get("body"))[:3]:
        try:
            issue = gh.get(f"/issues/{issue_number}")
        except urllib.error.HTTPError:
            continue
        competing = [
            item["number"]
            for item in search_items(gh, f'is:pr is:open "#{issue_number}"', 10)
            if item["number"] != number
        ]
        linked.append(
            {
                "number": issue_number,
                "title": issue["title"],
                "state": issue["state"],
                "is_pr": bool(issue.get("pull_request")),
                "assignees": [a["login"] for a in issue.get("assignees", [])],
                "labels": [label["name"] for label in issue.get("labels", [])],
                "other_open_prs": competing,
            }
        )
    paths = [f["filename"] for f in files]
    return {
        "number": number,
        "url": pr["html_url"],
        "title": pr["title"],
        "body": truncate(pr.get("body"), BODY_LIMIT),
        "body_has_media": has_media(pr.get("body")),
        "draft": pr.get("draft"),
        "state": pr["state"],
        "head_sha": sha,
        "base": pr["base"]["ref"],
        "mergeable_state": pr.get("mergeable_state"),
        "labels": [label["name"] for label in pr.get("labels", [])],
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
        "author": author_facts(gh, pr["user"]["login"], pr.get("author_association")),
        "size": {"additions": pr["additions"], "deletions": pr["deletions"], "files": pr["changed_files"]},
        **classify_paths(paths),
        "files": [
            {"path": f["filename"], "status": f["status"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in files[:FILES_LIMIT]
        ],
        "dependencies": dependency_changes(files),
        "linked_issues": linked,
        "ci": ci_state(check_runs, workflow_runs, statuses),
        "coderabbit": coderabbit_facts(gh, number, statuses),
        "human_reviews": latest_review,
        "last_bot_review": last_marker,
        "recent_comments": [
            comment_view(c)
            for c in comments
            if (c.get("user") or {}).get("type") != "Bot" and (c.get("user") or {}).get("login") != bot
        ][-8:],
        "similar_open_prs": similar_items(gh, number, pr["title"], "is:pr is:open"),
        "new_settings": new_settings(files),
        "diff_excerpt": diff_excerpt(files),
    }


def prs_for_sha(gh: GitHub, sha: str) -> list[int]:
    """Open PRs a search associates with ``sha``; callers check the head themselves.

    Unlike the optional searches this one is not allowed to fail quietly: with no
    PR found the review would be skipped unseen, so an error fails the run instead.
    """
    items = gh.search(f"is:pr is:open {sha}", limit=5).get("items", [])
    return [item["number"] for item in items]


def labels_available(gh: GitHub) -> list[dict[str, str]]:
    """The repo's labels, so the agent never invents one."""
    return [{"name": label["name"], "description": label.get("description") or ""} for label in gh.pages("/labels")]


def build_payload(
    kind: str, facts: dict[str, Any], gh: GitHub, mode: str, bot: str, trigger: Optional[dict] = None
) -> dict[str, Any]:
    """The JSON body the agent receives."""
    subject = "pr" if kind.startswith("pr_") else "issue"
    return {
        "kind": kind,
        "mode": mode,
        "repo": gh.repo,
        "bot_login": bot,
        "now": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trigger": trigger or {},
        "labels_available": labels_available(gh),
        subject: facts,
    }


def write_job(out_dir: str, index: int, kind: str, number: int, payload: dict[str, Any], key: str) -> str:
    """Write one payload file and append its ``key<TAB>path`` line to ``jobs.tsv``."""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{index:02d}-{kind}-{number}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    with open(os.path.join(out_dir, "jobs.tsv"), "a", encoding="utf-8") as handle:
        handle.write(f"{key[:256]}\t{path}\n")
    return path


def review_is_due(facts: dict[str, Any], maintainers: Maintainers, bot: str) -> Optional[str]:
    """Why an automatic ``pr_review`` should wait or be skipped, or None when it is due."""
    author = facts["author"]
    if author.get("type") == "Bot" or author["login"] == bot:
        return "authored by a bot"
    if facts["draft"] or maintainers.includes(author["login"], author["association"]):
        return "draft, or authored by a maintainer"
    if facts["ci"]["state"] == "pending" or facts["coderabbit"]["status"] == "pending":
        return "checks still running, a later event will review it"
    last = facts["last_bot_review"] or {}
    if last.get("verdict") != "opened" and last.get("sha") == facts["head_sha"] and last.get("ci") == facts["ci"]["state"]:
        return f"already reviewed at {facts['head_sha'][:7]} with CI {facts['ci']['state']}"
    return None


def mark_maintainer(person: dict[str, Any], maintainers: Maintainers) -> dict[str, Any]:
    """Add ``is_maintainer`` to an author's facts."""
    person["is_maintainer"] = maintainers.includes(person.get("login"), person.get("association"))
    return person


def jobs_for(
    gh: GitHub,
    decision: dict[str, Any],
    event: dict[str, Any],
    bot: str,
    maintainers: Maintainers,
    manual: bool = False,
) -> list[tuple[str, dict[str, Any], str, dict]]:
    """Expand a routing decision into ``(kind, facts, idempotency_key, trigger)`` jobs."""
    kind = decision["kind"]
    if kind.startswith("issue_"):
        number = decision["number"]
        facts = issue_facts(gh, number, bot, maintainers)
        mark_maintainer(facts["author"], maintainers)
        trigger: dict[str, Any] = {}
        key = f"issue-{number}-{kind}"
        if "comment_id" in decision:
            comment = gh.get(f"/issues/comments/{decision['comment_id']}")
            login = comment["user"]["login"]
            commenter = mark_maintainer(author_facts(gh, login, comment.get("author_association")), maintainers)
            if kind == "issue_claim":
                since = parse_time(comment["created_at"]) - timedelta(minutes=CLAIM_WINDOW_MINUTES)
                recent = gh.pages("/issues/comments", limit=300, since=since.strftime("%Y-%m-%dT%H:%M:%SZ"))
                assigned = assigned_open_issues(gh, login) or []
                pending = pending_claims(recent, login, comment["created_at"], number, assigned)
                commenter["claims_pending_elsewhere"] = pending
                commenter["open_assignments"] = len(assigned) + len(pending)
            trigger = {"comment": comment_view(comment), "commenter": commenter}
            key += f"-{decision['comment_id']}"
        return [(kind, facts, key, trigger)]
    if "number" in decision:
        numbers = [decision["number"]]
    else:
        numbers = decision.get("numbers") or prs_for_sha(gh, decision["sha"])
    jobs = []
    for number in numbers:
        if not manual:
            author = gh.get(f"/pulls/{number}").get("user") or {}
            if author.get("type") == "Bot" or author.get("login") == bot:
                print(f"PR #{number}: authored by a bot")
                continue
        facts = pr_facts(gh, number, bot)
        mark_maintainer(facts["author"], maintainers)
        if "sha" in decision and facts["head_sha"] != decision["sha"]:
            print(f"PR #{number}: head is {facts['head_sha'][:7]}, not the event's {decision['sha'][:7]}")
            continue
        reason = None if manual or kind != "pr_review" else review_is_due(facts, maintainers, bot)
        if reason:
            print(f"PR #{number}: {reason}")
            continue
        key = f"pr-{number}-{kind}-{facts['head_sha']}-{facts['ci']['state']}"
        jobs.append((kind, facts, key, {}))
    return jobs


def main(argv: Optional[list[str]] = None) -> int:
    """Route the current event (or a manual target) to the triage agent."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--issue", type=int, help="triage this issue")
    target.add_argument("--pr", type=int, help="review this pull request")
    parser.add_argument("--out", help="write payloads and jobs.tsv here instead of printing them")
    args = parser.parse_args(argv)

    repo = os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO
    bot = os.environ.get("TRIAGE_BOT_LOGIN") or DEFAULT_BOT
    mode = "live" if os.environ.get("TRIAGE_MODE") == "live" else "shadow"
    maintainers = Maintainers.from_env(os.environ.get("TRIAGE_MAINTAINERS"), os.environ.get("TRIAGE_SKIP_ASSOCIATIONS"))
    gh = GitHub(os.environ.get("GITHUB_TOKEN"), repo)

    event: dict[str, Any] = {}
    if args.issue:
        decision: dict[str, Any] = {"kind": "issue_opened", "number": args.issue}
    elif args.pr:
        decision = {"kind": "pr_review", "number": args.pr}
    else:
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
            event = json.load(handle)
        if event_name == "workflow_dispatch":
            inputs = event.get("inputs") or {}
            kind = "issue_opened" if inputs.get("target") == "issue" else "pr_review"
            decision = {"kind": kind, "number": int(inputs["number"])}
        else:
            decision = route(event_name, event, bot, maintainers)
    if not decision.get("kind"):
        print(f"Skipped: {decision.get('reason')}")
        return 0

    manual = bool(args.issue or args.pr or event.get("inputs"))
    jobs = jobs_for(gh, decision, event, bot, maintainers, manual)
    for index, (kind, facts, key, trigger) in enumerate(jobs):
        if manual:
            trigger = {**trigger, "manual": True}
            key += f"-manual-{now_utc():%Y%m%d%H%M%S}"
        payload = build_payload(kind, facts, gh, mode, bot, trigger)
        size = len(json.dumps(payload))
        if args.out:
            write_job(args.out, index, kind, facts["number"], payload, key)
            print(f"{kind} #{facts['number']} ({mode}, {size} chars) ready, key {key}")
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            print(f"[{kind} #{facts['number']}: {size} chars, key {key}]", file=sys.stderr)
    if not jobs:
        print("Nothing to send")
    return 0


if __name__ == "__main__":
    sys.exit(main())
