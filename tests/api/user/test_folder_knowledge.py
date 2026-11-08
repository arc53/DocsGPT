"""Live knowledge folders: expansion, the attach gate and folder details (``api/user/folder_knowledge``)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.api.user.folder_knowledge import (
    FolderRefError,
    caller_folder_source_ids,
    expand_folders,
    folder_details,
    folder_source_ids,
    owned_source_folders,
    parse_folder_refs,
    unattachable_folder,
)
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository

OWNER, MATE, STRANGER = "k-owner", "k-mate", "k-stranger"


def _folder(conn, name, *, owner=OWNER, parent=None, type_="source"):
    return str(FoldersRepository(conn).create(owner, name, resource_type=type_, parent_id=parent)["id"])


def _source(conn, name, owner=OWNER):
    return str(SourcesRepository(conn).create(name, user_id=owner)["id"])


def _file(conn, source_id, folder_id, user=OWNER):
    FolderItemsRepository(conn).file(user, "source", source_id, folder_id)


def _share(conn, source_id, owner, member, level="viewer"):
    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "source", source_id, owner, owner, access_level=level, target_user_id=member
    )


class TestParseFolderRefs:
    def test_none_and_empty_mean_no_folders(self):
        assert parse_folder_refs(None) == []
        assert parse_folder_refs("") == []
        assert parse_folder_refs([]) == []

    def test_lower_cases_and_dedupes(self):
        fid = str(uuid.uuid4())
        assert parse_folder_refs([fid.upper(), fid, f" {fid} "]) == [fid]

    @pytest.mark.parametrize("raw", ["abc", {"id": "x"}, 7])
    def test_must_be_a_list(self, raw):
        with pytest.raises(FolderRefError, match="must be a list"):
            parse_folder_refs(raw)

    @pytest.mark.parametrize("item", ["not-a-uuid", 7, None, {"id": "x"}])
    def test_every_entry_must_be_a_folder_id(self, item):
        with pytest.raises(FolderRefError, match="Invalid folder ID"):
            parse_folder_refs([str(uuid.uuid4()), item])


class TestExpansion:
    def test_reads_the_owners_filings_across_the_subtree(self, pg_conn):
        top = _folder(pg_conn, "Carriers")
        child = _folder(pg_conn, "EU", parent=top)
        grandchild = _folder(pg_conn, "Rail", parent=child)
        sibling = _folder(pg_conn, "Other")
        a, b, c, d = (_source(pg_conn, n) for n in ("b-top", "a-child", "c-deep", "elsewhere"))
        _file(pg_conn, a, top)
        _file(pg_conn, b, child)
        _file(pg_conn, c, grandchild)
        _file(pg_conn, d, sibling)
        assert expand_folders(pg_conn, [top]) == {top: [a, b, c]}
        assert expand_folders(pg_conn, [child]) == {child: [b, c]}
        assert folder_source_ids(pg_conn, [child, top]) == [b, c, a]

    def test_another_users_filing_into_the_same_source_does_not_count(self, pg_conn):
        mine = _folder(pg_conn, "Mine")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        shared = _source(pg_conn, "shared")
        _share(pg_conn, shared, OWNER, MATE)
        _file(pg_conn, shared, theirs, user=MATE)
        assert expand_folders(pg_conn, [mine]) == {mine: []}
        assert expand_folders(pg_conn, [theirs]) == {theirs: [shared]}

    def test_only_sources_the_folder_owner_may_use(self, pg_conn):
        folder = _folder(pg_conn, "Mixed", owner=MATE)
        shared = _source(pg_conn, "shared")
        revoked = _source(pg_conn, "revoked")
        _share(pg_conn, shared, OWNER, MATE)
        _file(pg_conn, shared, folder, user=MATE)
        # A filing of a source whose share ended stays, hidden; it must not be read.
        _file(pg_conn, revoked, folder, user=MATE)
        assert expand_folders(pg_conn, [folder]) == {folder: [shared]}

    def test_missing_folders_and_agent_folders_are_skipped(self, pg_conn):
        agent_folder = _folder(pg_conn, "Agents", type_="agent")
        gone = str(uuid.uuid4())
        assert expand_folders(pg_conn, [gone, agent_folder, "junk"]) == {}
        assert folder_source_ids(pg_conn, [gone]) == []

    def test_deduped_across_folders_ignoring_case(self, pg_conn):
        one = _folder(pg_conn, "One")
        two = _folder(pg_conn, "Two", owner=MATE)
        sid = _source(pg_conn, "both")
        _share(pg_conn, sid, OWNER, MATE)
        _file(pg_conn, sid, one)
        _file(pg_conn, sid, two, user=MATE)
        assert folder_source_ids(pg_conn, [one.upper(), two, one]) == [sid]

    def test_a_deleted_source_drops_out(self, pg_conn):
        folder = _folder(pg_conn, "F")
        sid = _source(pg_conn, "s")
        _file(pg_conn, sid, folder)
        pg_conn.execute(text("DELETE FROM sources WHERE id = CAST(:id AS uuid)"), {"id": sid})
        assert expand_folders(pg_conn, [folder]) == {folder: []}

    def test_caller_folders_only(self, pg_conn):
        mine = _folder(pg_conn, "Mine")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        a = _source(pg_conn, "a")
        b = _source(pg_conn, "b", owner=MATE)
        _file(pg_conn, a, mine)
        _file(pg_conn, b, theirs, user=MATE)
        assert caller_folder_source_ids(pg_conn, [mine, theirs], OWNER) == [a]
        assert caller_folder_source_ids(pg_conn, [mine, theirs], None) == []


class TestAttachGate:
    def test_only_the_owners_source_folders(self, pg_conn):
        mine = _folder(pg_conn, "Mine")
        agent_folder = _folder(pg_conn, "Agents", type_="agent")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        assert owned_source_folders(pg_conn, [mine, agent_folder, theirs], OWNER) == [mine]
        assert unattachable_folder(pg_conn, [mine], OWNER) is None
        assert unattachable_folder(pg_conn, [mine, theirs], OWNER) == theirs
        assert unattachable_folder(pg_conn, [agent_folder], OWNER) == agent_folder
        assert unattachable_folder(pg_conn, [str(uuid.uuid4())], OWNER) is not None

    def test_folders_already_attached_stay(self, pg_conn):
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        assert unattachable_folder(pg_conn, [theirs], OWNER, existing=[theirs.upper()]) is None


class TestDetails:
    def test_names_counts_and_owner(self, pg_conn):
        pg_conn.execute(
            text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT (user_id) DO UPDATE SET email = :e"),
            {"u": MATE, "e": "mate@example.com"},
        )
        mine = _folder(pg_conn, "Mine")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        _file(pg_conn, _source(pg_conn, "a"), mine)
        gone = str(uuid.uuid4())
        assert folder_details(pg_conn, [mine, theirs, gone], OWNER) == [
            {"id": mine, "name": "Mine", "source_count": 1},
            {"id": theirs, "name": "Theirs", "source_count": 0, "owner_name": "mate@example.com"},
            {"id": gone, "name": None, "source_count": 0},
        ]
        assert folder_details(pg_conn, [], OWNER) == []
