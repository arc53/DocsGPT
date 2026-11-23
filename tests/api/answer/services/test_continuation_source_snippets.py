"""Client-facing source excerpts stay on the matched child when a pause retires."""

from unittest.mock import MagicMock, patch

from docsgpt.storage.db.repositories.conversations import MessageUpdateOutcome


def test_retired_pause_persists_matched_text_and_handles_mapped_sources():
    from docsgpt.api.answer.services.continuation_service import retire_paused_message
    from docsgpt.connectors.attribution import client_sources

    message_id = "22222222-2222-2222-2222-222222222222"
    already_mapped = client_sources([{"text": "CHILD", "matched_text": "CHILD", "filename": "b.pdf"}])[0]
    retrieved_docs = [
        {"text": "PARENT CHILD", "matched_text": "CHILD", "filename": "a.pdf"},
        already_mapped,
    ]
    state = {
        "agent_config": {"reserved_message_id": message_id, "retrieved_docs": retrieved_docs},
        "pending_tool_calls": [],
        "user_id": "user-1",
    }
    partial = {"response": "answer", "thought": "", "tool_calls": [], "sources": [], "segments": []}
    repo = MagicMock()
    repo.update_message_by_id.return_value = MessageUpdateOutcome.UPDATED

    with (
        patch(
            "docsgpt.storage.db.repositories.message_events.MessageEventsRepository"
        ) as event_repo,
        patch(
            "docsgpt.api.answer.services.continuation_service.ConversationsRepository",
            return_value=repo,
        ),
        patch("docsgpt.monitors.secret_refs.exposed_values", return_value={}),
    ):
        event_repo.return_value.reconstruct_partial.return_value = partial
        result = retire_paused_message(MagicMock(), state, "moved_on")

    assert result == message_id
    saved_sources = repo.update_message_by_id.call_args.args[1]["sources"]
    assert [source["text"] for source in saved_sources] == ["CHILD", "CHILD"]
    assert all("matched_text" not in source for source in saved_sources)
    assert retrieved_docs[0]["text"] == "PARENT CHILD"
