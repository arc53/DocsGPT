"""/v1 with inline files: the pre-check before storage treats the key holder as an outside caller.

A request carrying files is checked against the limits before its files are stored. The key holder is outside
traffic, so when the agent's payer is out of allowance they are told only that the agent is paused: no usage,
limit or bucket, and the quota provider is never asked to decorate a refusal with the payer's id.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from docsgpt.api.owner_pause import PAUSED_CODE
from docsgpt.api.v1.routes import _V1AnswerHelper
from docsgpt.quotas import providers
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from tests.api.v1.test_v1_file_attachments_route import BODY, _post, _processor

pytestmark = pytest.mark.unit

_NUMBERS = ("usage", "limit", "bucket", "dimension", "unit", "resets_at", "source")


class _RecordingProvider(providers.QuotaDefaultsProvider):
    """A cloud-style provider that remembers whose refusal it decorated."""

    def __init__(self) -> None:
        self.decorated_for: list = []

    def error_payload(self, payload: dict, user_id: str) -> dict:
        self.decorated_for.append(user_id)
        return {**payload, "upgrade_url": f"https://example.test/upgrade?u={user_id}"}


@pytest.fixture
def db(pg_conn, monkeypatch):
    @contextmanager
    def _yield():
        yield pg_conn

    for target in (
        "docsgpt.quotas.service.db_readonly",
        "docsgpt.quotas.payer.db_readonly",
        "docsgpt.api.answer.routes.base.db_readonly",
    ):
        monkeypatch.setattr(target, _yield)
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")
    return pg_conn


@pytest.fixture
def provider(monkeypatch):
    recording = _RecordingProvider()
    monkeypatch.setattr(providers, "_provider", recording)
    return recording


@pytest.mark.parametrize("stream", [False, True])
def test_a_key_holder_with_files_is_told_only_that_the_agent_is_paused(db, provider, stream):
    # ``_patch_v1_db`` publishes key ``x`` on a personal agent owned by ``u-test``, who has used up their allowance.
    QuotaPoliciesRepository(db).upsert(scope="user", subject_id="u-test", token_limit=100)
    TokenUsageRepository(db).insert(user_id="u-test", prompt_tokens=100)
    processor = _processor()

    response, _, _, ingested = _post(db, {**BODY, "stream": stream}, processor, _V1AnswerHelper(), pending=True)

    assert response.status_code == 429
    body = response.get_json()
    # The OpenAI error shape every other /v1 error uses.
    assert body["error"]["code"] == PAUSED_CODE
    assert body["error"]["type"] == "rate_limit_error"
    assert not set(_NUMBERS) & set(body) and not set(_NUMBERS) & set(body["error"])
    assert response.headers["x-should-retry"] == "false"
    assert "u-test" not in response.get_data(as_text=True)
    assert provider.decorated_for == []
    ingested.assert_not_called()
    processor.build_agent.assert_not_called()
