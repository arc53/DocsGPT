"""The sources an agent's topic question reads: its own refs and what its knowledge folders feed (``pg_conn``)."""

from __future__ import annotations

import uuid

from docsgpt.analytics import topics
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository

OWNER, MATE = "t-owner", "t-mate"


def _folder(conn, name, owner=OWNER, parent=None):
    return str(FoldersRepository(conn).create(owner, name, resource_type="source", parent_id=parent)["id"])


def _source(conn, name, owner=OWNER, structure=None):
    return str(SourcesRepository(conn).create(name, user_id=owner, directory_structure=structure)["id"])


def _agent(**fields):
    return {"id": str(uuid.uuid4()), "user_id": OWNER, **fields}


class TestAgentSources:
    def test_reads_the_sources_its_knowledge_folders_feed_each_once(self, pg_conn):
        direct, filed, deep = (_source(pg_conn, n) for n in ("direct", "filed", "deep"))
        top = _folder(pg_conn, "Carriers")
        child = _folder(pg_conn, "EU", parent=top)
        items = FolderItemsRepository(pg_conn)
        items.file(OWNER, "source", filed, top)
        items.file(OWNER, "source", deep, child)
        items.file(OWNER, "source", direct, child)
        agent = _agent(source_id=direct, knowledge_folder_ids=[top, str(uuid.uuid4())])
        ids = [str(row["id"]) for row in topics.agent_sources(pg_conn, agent)]
        assert sorted(ids) == sorted([direct, filed, deep])

    def test_a_folder_only_agent_has_sources(self, pg_conn):
        filed = _source(pg_conn, "filed")
        folder = _folder(pg_conn, "Docs")
        FolderItemsRepository(pg_conn).file(OWNER, "source", filed, folder)
        agent = _agent(knowledge_folder_ids=[folder])
        assert [str(row["id"]) for row in topics.agent_sources(pg_conn, agent)] == [filed]

    def test_a_folder_feeds_what_a_run_reads(self, pg_conn):
        # A teammate's folder on an agent they cannot edit feeds a run nothing, so it gives no topic folders either.
        theirs = _source(pg_conn, "theirs", owner=MATE)
        folder = _folder(pg_conn, "Mate's", owner=MATE)
        FolderItemsRepository(pg_conn).file(MATE, "source", theirs, folder)
        assert topics.agent_sources(pg_conn, _agent(knowledge_folder_ids=[folder])) == []

    def test_folder_sources_give_topic_folders(self, pg_conn):
        page = {"token_count": 10}
        one = _source(pg_conn, "one", structure={"install": {"a.md": page}})
        two = _source(pg_conn, "two", structure={"billing": {"b.md": page}})
        folder = _folder(pg_conn, "Docs")
        FolderItemsRepository(pg_conn).file(OWNER, "source", two, folder)
        agent = _agent(source_id=one, knowledge_folder_ids=[folder])
        assert sorted(f["name"] for f in topics.folders_of(pg_conn, agent)) == ["billing", "install"]
