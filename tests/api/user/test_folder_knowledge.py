"""Live knowledge folders: expansion, the attach gate and folder details (``api/user/folder_knowledge``)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.api.user.folder_knowledge import (
    FolderRefError,
    caller_folder_source_ids,
    expand_folders,
    expand_folders_of_holders,
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

    def test_missing_folders_are_skipped(self, pg_conn):
        # One tree: a folder made from the agents page reads like any other (no sources filed: empty).
        agent_folder = _folder(pg_conn, "Agents", type_="agent")
        gone = str(uuid.uuid4())
        assert expand_folders(pg_conn, [gone, agent_folder, "junk"]) == {agent_folder: []}
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


class TestExpansionOfSeveralHolders:
    def test_each_holder_gets_what_its_own_expansion_gives_from_one_load(self, pg_conn):
        from sqlalchemy import event

        from docsgpt.storage.db.repositories.agents import AgentsRepository

        _teammates(pg_conn, OWNER, MATE)
        mine = _folder(pg_conn, "Mine")
        child = _folder(pg_conn, "Child", parent=mine)
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        _file(pg_conn, _source(pg_conn, "a"), mine)
        _file(pg_conn, _source(pg_conn, "deep"), child)
        _file(pg_conn, _source(pg_conn, "stray", owner=STRANGER), mine)
        _file(pg_conn, _source(pg_conn, "b", owner=MATE), theirs, user=MATE)
        agents = AgentsRepository(pg_conn)
        owners_bot = agents.create(OWNER, "Owner's", "draft", knowledge_folder_ids=[mine, theirs])
        mates_bot = agents.create(MATE, "Mate's", "draft", knowledge_folder_ids=[theirs])
        holders = [
            ("agent", owners_bot, [mine, theirs, str(uuid.uuid4())]),
            ("agent", mates_bot, [theirs]),
            ("agent", mates_bot, []),
            ("workflow", {"user_id": OWNER}, [child]),
        ]
        alone = [expand_folders(pg_conn, ids, kind, holder) for kind, holder, ids in holders]
        statements: list[str] = []

        def _count(_conn, _cursor, statement, *args):
            statements.append(statement)

        event.listen(pg_conn, "before_cursor_execute", _count)
        try:
            together = expand_folders_of_holders(pg_conn, holders)
        finally:
            event.remove(pg_conn, "before_cursor_execute", _count)
        assert together == alone
        # Mate can't edit the owner's agent, so their folder feeds it nothing; the rest feed what they hold.
        assert together[0][theirs] == [] and len(together[0][mine]) == 2
        assert len(together[1][theirs]) == 1 and together[2] == {} and len(together[3][child]) == 1
        assert sum("WITH RECURSIVE tree" in s for s in statements) == 1
        assert expand_folders_of_holders(pg_conn, []) == []


class TestAttachGate:
    def test_only_the_owners_folders(self, pg_conn):
        mine = _folder(pg_conn, "Mine")
        # One tree: a folder made from the agents page is a knowledge folder too.
        agent_folder = _folder(pg_conn, "Agents", type_="agent")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        assert sorted(owned_source_folders(pg_conn, [mine, agent_folder, theirs], OWNER)) == sorted(
            [mine, agent_folder]
        )
        assert unattachable_folder(pg_conn, [mine], OWNER) is None
        assert unattachable_folder(pg_conn, [mine, theirs], OWNER) == theirs
        assert unattachable_folder(pg_conn, [agent_folder], OWNER) is None
        assert unattachable_folder(pg_conn, [str(uuid.uuid4())], OWNER) is not None

    def test_folders_already_attached_stay(self, pg_conn):
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        assert unattachable_folder(pg_conn, [theirs], OWNER, existing=[theirs.upper()]) is None


def _email(conn, user_id, email):
    conn.execute(
        text("INSERT INTO users (user_id, email) VALUES (:u, :e) ON CONFLICT (user_id) DO UPDATE SET email = :e"),
        {"u": user_id, "e": email},
    )


def _teammates(conn, *users):
    team = TeamsRepository(conn).create("T", f"t-{uuid.uuid4().hex[:8]}", users[0])
    for user in users:
        TeamMembersRepository(conn).add_member(str(team["id"]), user)


class TestDetails:
    def test_names_counts_and_owner(self, pg_conn):
        _email(pg_conn, MATE, "mate@example.com")
        _teammates(pg_conn, OWNER, MATE)
        mine = _folder(pg_conn, "Mine")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        _file(pg_conn, _source(pg_conn, "a"), mine)
        gone = str(uuid.uuid4())
        assert folder_details(pg_conn, [mine, theirs, gone], OWNER) == [
            {"id": mine, "name": "Mine", "source_count": 1},
            {"id": theirs, "name": "Theirs", "source_count": 0, "owner_id": MATE, "owner_name": "mate@example.com"},
            {"id": gone, "name": None, "source_count": 0, "stopped": True, "reason": "deleted"},
        ]
        assert folder_details(pg_conn, [], OWNER) == []

    def test_an_owner_without_an_email_is_named_by_id_like_a_sponsor(self, pg_conn):
        _teammates(pg_conn, OWNER, MATE)
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        [entry] = folder_details(pg_conn, [theirs], OWNER)
        assert (entry["owner_id"], entry["owner_name"]) == (MATE, MATE)

    def test_an_owner_the_reader_does_not_know_stays_unnamed(self, pg_conn):
        _email(pg_conn, STRANGER, "stranger@example.com")
        theirs = _folder(pg_conn, "Theirs", owner=STRANGER)
        assert folder_details(pg_conn, [theirs], OWNER) == [{"id": theirs, "name": "Theirs", "source_count": 0}]

    def test_the_holders_owner_is_named_to_its_reader(self, pg_conn):
        _email(pg_conn, MATE, "mate@example.com")
        theirs = _folder(pg_conn, "Theirs", owner=MATE)
        [entry] = folder_details(pg_conn, [theirs], OWNER, "agent", {"user_id": MATE})
        assert entry["owner_name"] == "mate@example.com"
