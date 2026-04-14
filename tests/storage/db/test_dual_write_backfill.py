"""Integration coverage for dual-write rows surviving backfill reruns."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from bson.dbref import DBRef
from flask import Flask, request

from application.core.settings import settings
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.dual_write import dual_write
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.attachments import AttachmentsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.shared_conversations import SharedConversationsRepository
from application.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from application.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from application.storage.db.repositories.workflows import WorkflowsRepository
from scripts.db.backfill import (
    _backfill_agents,
    _backfill_attachments,
    _backfill_conversations,
    _backfill_prompts,
    _backfill_shared_conversations,
    _backfill_workflow_runs,
    _backfill_workflow_nodes,
    _backfill_workflows,
)


pytestmark = pytest.mark.skipif(
    not settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


class _BoundEngine:
    """Expose one pre-opened SQLAlchemy connection as an Engine.begin()."""

    def __init__(self, conn):
        self._conn = conn

    @contextmanager
    def begin(self):
        yield self._conn


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def mongo_db(mock_mongo_db):
    return mock_mongo_db[settings.MONGO_DB_NAME]


@pytest.fixture
def dual_write_pg(monkeypatch, pg_conn):
    monkeypatch.setattr(settings, "USE_POSTGRES", True)
    monkeypatch.setattr(
        "application.storage.db.engine.get_engine",
        lambda: _BoundEngine(pg_conn),
    )
    return pg_conn


def test_prompt_dual_write_row_survives_backfill_rerun(app, mongo_db, dual_write_pg, monkeypatch):
    from application.api.user.prompts.routes import CreatePrompt

    monkeypatch.setattr(
        "application.api.user.prompts.routes.prompts_collection",
        mongo_db["prompts"],
    )

    with app.test_request_context(
        "/api/create_prompt",
        method="POST",
        json={"name": "Greeting", "content": "Hello"},
    ):
        request.decoded_token = {"sub": "user-1"}
        response = CreatePrompt().post()

    assert response.status_code == 200
    mongo_id = response.json["id"]

    repo = PromptsRepository(dual_write_pg)
    prompt = repo.get_by_legacy_id(mongo_id, "user-1")
    assert prompt is not None
    assert prompt["content"] == "Hello"

    mongo_db["prompts"].update_one(
        {"_id": ObjectId(mongo_id)},
        {"$set": {"content": "Hello again"}},
    )
    _backfill_prompts(conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False)

    prompts = repo.list_for_user("user-1")
    assert len(prompts) == 1
    assert prompts[0]["legacy_mongo_id"] == mongo_id
    assert prompts[0]["content"] == "Hello again"


def test_agent_dual_write_row_survives_backfill_rerun(app, mongo_db, dual_write_pg, monkeypatch):
    from application.api.user.agents.routes import CreateAgent

    monkeypatch.setattr(
        "application.api.user.agents.routes.agents_collection",
        mongo_db["agents"],
    )
    monkeypatch.setattr(
        "application.api.user.agents.routes.handle_image_upload",
        lambda *_args, **_kwargs: ("", None),
    )

    with app.test_request_context(
        "/api/create_agent",
        method="POST",
        json={"name": "Mirror Agent", "status": "draft"},
    ):
        request.decoded_token = {"sub": "user-1"}
        response = CreateAgent().post()

    assert response.status_code == 201
    mongo_id = response.json["id"]

    repo = AgentsRepository(dual_write_pg)
    agent = repo.get_by_legacy_id(mongo_id, "user-1")
    assert agent is not None
    assert agent["name"] == "Mirror Agent"

    mongo_db["agents"].update_one(
        {"_id": ObjectId(mongo_id)},
        {"$set": {"name": "Renamed Agent", "description": "Updated by backfill"}},
    )
    _backfill_agents(conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False)

    agents = repo.list_for_user("user-1")
    assert len(agents) == 1
    assert agents[0]["legacy_mongo_id"] == mongo_id
    assert agents[0]["name"] == "Renamed Agent"
    assert agents[0]["description"] == "Updated by backfill"


def test_attachment_dual_write_row_survives_backfill_rerun(mongo_db, dual_write_pg):
    mongo_id = ObjectId()
    mongo_db["attachments"].insert_one(
        {
            "_id": mongo_id,
            "user": "user-1",
            "filename": "notes.txt",
            "upload_path": "/uploads/notes.txt",
            "mime_type": "text/plain",
            "size": 12,
        }
    )

    dual_write(
        AttachmentsRepository,
        lambda repo: repo.create(
            "user-1",
            "notes.txt",
            "/uploads/notes.txt",
            mime_type="text/plain",
            size=12,
            legacy_mongo_id=str(mongo_id),
        ),
    )

    repo = AttachmentsRepository(dual_write_pg)
    attachment = repo.get_by_legacy_id(str(mongo_id), "user-1")
    assert attachment is not None
    assert attachment["filename"] == "notes.txt"

    mongo_db["attachments"].update_one(
        {"_id": mongo_id},
        {"$set": {"filename": "notes-v2.txt", "size": 24}},
    )
    _backfill_attachments(conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False)

    attachments = repo.list_for_user("user-1")
    assert len(attachments) == 1
    assert attachments[0]["legacy_mongo_id"] == str(mongo_id)
    assert attachments[0]["filename"] == "notes-v2.txt"
    assert attachments[0]["size"] == 24


def test_workflow_nodes_dual_write_rows_survive_backfill_rerun(mongo_db, dual_write_pg, monkeypatch):
    from application.api.user.workflows.routes import (
        _dual_write_workflow_create,
        create_workflow_edges,
        create_workflow_nodes,
    )

    monkeypatch.setattr(
        "application.api.user.workflows.routes.workflows_collection",
        mongo_db["workflows"],
    )
    monkeypatch.setattr(
        "application.api.user.workflows.routes.workflow_nodes_collection",
        mongo_db["workflow_nodes"],
    )
    monkeypatch.setattr(
        "application.api.user.workflows.routes.workflow_edges_collection",
        mongo_db["workflow_edges"],
    )

    workflow_doc = {
        "name": "Workflow",
        "description": "test",
        "user": "user-1",
        "current_graph_version": 1,
    }
    insert_result = mongo_db["workflows"].insert_one(workflow_doc)
    workflow_id = str(insert_result.inserted_id)
    nodes_data = [
        {"id": "start", "type": "start", "title": "Start"},
        {"id": "end", "type": "end", "title": "End"},
    ]
    edges_data = [{"id": "edge-1", "source": "start", "target": "end"}]

    created_nodes = create_workflow_nodes(workflow_id, nodes_data, 1)
    create_workflow_edges(workflow_id, edges_data, 1)
    _dual_write_workflow_create(
        workflow_id,
        "user-1",
        "Workflow",
        "test",
        created_nodes,
        edges_data,
    )

    workflow_repo = WorkflowsRepository(dual_write_pg)
    workflow = workflow_repo.list_for_user("user-1")[0]
    node_repo = WorkflowNodesRepository(dual_write_pg)
    pg_nodes = node_repo.find_by_version(workflow["id"], 1)
    assert len(pg_nodes) == 2
    assert all(node["legacy_mongo_id"] for node in pg_nodes)

    renamed_node_id = created_nodes[0]["legacy_mongo_id"]
    mongo_db["workflow_nodes"].update_one(
        {"_id": ObjectId(renamed_node_id)},
        {"$set": {"title": "Renamed Start"}},
    )

    _backfill_workflows(conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False)
    _backfill_workflow_nodes(conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False)

    pg_nodes = node_repo.find_by_version(workflow["id"], 1)
    assert len(pg_nodes) == 2
    renamed_node = node_repo.get_by_legacy_id(renamed_node_id)
    assert renamed_node is not None
    assert renamed_node["title"] == "Renamed Start"


def test_compression_summary_dual_write_appends_pg_message(mongo_db, dual_write_pg):
    from application.api.answer.services.conversation_service import ConversationService

    mongo_conv_id = ObjectId()
    mongo_db["conversations"].insert_one(
        {"_id": mongo_conv_id, "user": "user-1", "queries": []},
    )
    conv = ConversationsRepository(dual_write_pg).create(
        "user-1", "Mirror", legacy_mongo_id=str(mongo_conv_id),
    )

    service = ConversationService()
    metadata = {
        "compressed_summary": "Compressed context summary",
        "timestamp": "2026-04-13T12:00:00+00:00",
        "model_used": "gpt-4",
    }
    service.append_compression_message(str(mongo_conv_id), metadata)

    pg_messages = ConversationsRepository(dual_write_pg).get_messages(conv["id"])
    assert len(pg_messages) == 1
    assert pg_messages[0]["prompt"] == "[Context Compression Summary]"
    assert pg_messages[0]["response"] == "Compressed context summary"
    assert pg_messages[0]["model_id"] == "gpt-4"


def test_workflow_run_dual_write_row_survives_backfill_rerun(mongo_db, dual_write_pg):
    from application.agents.workflow_agent import WorkflowAgent

    mongo_workflow_id = ObjectId()
    mongo_db["workflows"].insert_one(
        {
            "_id": mongo_workflow_id,
            "user": "user-1",
            "name": "Workflow",
            "description": "test",
        }
    )
    workflow = WorkflowsRepository(dual_write_pg).create(
        "user-1", "Workflow", description="test",
        legacy_mongo_id=str(mongo_workflow_id),
    )

    agent = WorkflowAgent(
        endpoint="https://api.example.com",
        llm_name="openai",
        model_id="gpt-4",
        api_key="test_key",
        user_api_key=None,
        prompt="You are helpful.",
        chat_history=[],
        decoded_token={"sub": "user-1"},
        attachments=[],
        json_schema=None,
        workflow_id=str(mongo_workflow_id),
        workflow_owner="user-1",
    )
    agent._engine = MagicMock()
    agent._engine.state = {"answer": "ok"}
    agent._engine.execution_log = []
    agent._engine.get_execution_summary.return_value = []

    agent._save_workflow_run("hello")

    run_repo = WorkflowRunsRepository(dual_write_pg)
    runs = run_repo.list_for_workflow(workflow["id"])
    assert len(runs) == 1
    assert runs[0]["user_id"] == "user-1"
    legacy_mongo_id = runs[0]["legacy_mongo_id"]

    mongo_db["workflow_runs"].update_one(
        {"_id": ObjectId(legacy_mongo_id)},
        {"$set": {"status": "failed", "user": "user-1", "user_id": "user-1"}},
    )
    _backfill_workflow_runs(
        conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False,
    )

    runs = run_repo.list_for_workflow(workflow["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["legacy_mongo_id"] == legacy_mongo_id


def test_shared_conversation_backfill_recovers_dbref_and_agent_prompt_metadata(
    mongo_db, dual_write_pg,
):
    conv = ConversationsRepository(dual_write_pg).create(
        "user-1", "Conversation", legacy_mongo_id="507f1f77bcf86cd799439011",
    )
    PromptsRepository(dual_write_pg).create(
        "user-1", "Prompt", "Body",
        legacy_mongo_id="507f1f77bcf86cd799439012",
    )

    mongo_db["agents"].insert_one(
        {
            "_id": ObjectId(),
            "key": "share-key",
            "prompt_id": ObjectId("507f1f77bcf86cd799439012"),
            "chunks": "7",
            "user": "user-1",
        }
    )
    mongo_db["shared_conversations"].insert_one(
        {
            "_id": ObjectId(),
            "uuid": "00000000-0000-0000-0000-000000000001",
            "conversation_id": DBRef(
                "conversations", ObjectId("507f1f77bcf86cd799439011"),
            ),
            "user": "user-1",
            "isPromptable": True,
            "first_n_queries": 2,
            "api_key": "share-key",
        }
    )

    _backfill_shared_conversations(
        conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False,
    )

    shares = SharedConversationsRepository(dual_write_pg).list_for_conversation(conv["id"])
    assert len(shares) == 1
    assert shares[0]["api_key"] == "share-key"
    assert shares[0]["chunks"] == 7
    assert shares[0]["prompt_id"] is not None


def test_conversation_backfill_reports_unresolved_attachment_refs(mongo_db, dual_write_pg):
    mongo_db["conversations"].insert_one(
        {
            "_id": ObjectId("507f1f77bcf86cd799439021"),
            "user": "user-1",
            "name": "Conversation",
            "queries": [
                {
                    "prompt": "q1",
                    "response": "a1",
                    "attachments": [str(ObjectId("507f1f77bcf86cd799439022"))],
                }
            ],
        }
    )

    stats = _backfill_conversations(
        conn=dual_write_pg, mongo_db=mongo_db, batch_size=50, dry_run=False,
    )

    assert stats["unresolved_attachment_refs"] == 1
    conv = ConversationsRepository(dual_write_pg).get_by_legacy_id(
        "507f1f77bcf86cd799439021",
    )
    messages = ConversationsRepository(dual_write_pg).get_messages(conv["id"])
    assert messages[0]["attachments"] == []
