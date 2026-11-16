"""Tests for AgentsRepository against a real Postgres instance."""

from __future__ import annotations

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository


def _repo(conn) -> AgentsRepository:
    return AgentsRepository(conn)


class TestCreate:
    def test_creates_agent_minimal(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("user-1", "My Agent", "draft")
        assert doc["user_id"] == "user-1"
        assert doc["name"] == "My Agent"
        assert doc["status"] == "draft"
        assert doc["id"] is not None

    def test_create_with_kwargs(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "user-1", "Agent2", "active",
            description="A test agent",
            chunks=5,
            tools=[{"name": "search"}],
            shared=True,
        )
        assert doc["description"] == "A test agent"
        assert doc["chunks"] == 5
        assert doc["tools"] == [{"name": "search"}]
        assert doc["shared"] is True

    def test_create_returns_id_and_underscore_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft")
        assert doc["_id"] == doc["id"]

    def test_create_with_legacy_mongo_id(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "u",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        assert doc["legacy_mongo_id"] == "507f1f77bcf86cd799439011"

    def test_create_with_resource_sponsors(self, pg_conn):
        repo = _repo(pg_conn)
        sponsors = {"tool:t1": "editor-1"}
        doc = repo.create("u", "a", "draft", resource_sponsors=sponsors)
        assert doc["resource_sponsors"] == sponsors

    def test_create_normalizes_blank_key_to_null(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", key="")
        assert doc["key"] is None


class TestGet:
    def test_get_existing(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        fetched = repo.get(created["id"], "user-1")
        assert fetched["id"] == created["id"]

    def test_get_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.get("00000000-0000-0000-0000-000000000000", "user-1") is None

    def test_get_wrong_user_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        assert repo.get(created["id"], "user-other") is None

    def test_find_image_record_returns_only_capability_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1", "a", "draft", image="inputs/user-1/attachments/a.png"
        )

        image_record = repo.find_image_record(str(created["id"]))

        assert set(image_record) >= {"id", "user_id", "image"}
        assert image_record["image"] == "inputs/user-1/attachments/a.png"
        assert "name" not in image_record

    def test_get_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["id"] == created["id"]


class TestFindByKey:
    def test_finds_agent_by_key(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft", key="my-unique-key")
        fetched = repo.find_by_key("my-unique-key")
        assert fetched["id"] == created["id"]

    def test_find_by_key_nonexistent_returns_none(self, pg_conn):
        repo = _repo(pg_conn)
        assert repo.find_by_key("nonexistent-key") is None


class TestSharing:
    def test_create_with_share_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=True,
            shared_token="share-abc",
            shared_metadata={"name": "public demo", "avatar": "🤖"},
        )
        assert created["shared"] is True
        assert created["shared_token"] == "share-abc"
        assert created["shared_metadata"] == {"name": "public demo", "avatar": "🤖"}

    def test_update_share_fields(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft")
        repo.update(
            created["id"], "u",
            {"shared": True, "shared_token": "tok-xyz", "shared_metadata": {"k": 1}},
        )
        fetched = repo.get(created["id"], "u")
        assert fetched["shared"] is True
        assert fetched["shared_token"] == "tok-xyz"
        assert fetched["shared_metadata"] == {"k": 1}

    def test_find_by_shared_token_only_returns_shared_agents(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=True, shared_token="tok-1",
        )
        found = repo.find_by_shared_token("tok-1")
        assert found is not None
        assert found["id"] == created["id"]

    def test_find_by_shared_token_skips_revoked(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "u", "a", "published",
            shared=False, shared_token="tok-revoked",
        )
        assert repo.find_by_shared_token("tok-revoked") is None
        # And revocation by flipping `shared` is immediately effective
        repo.update(created["id"], "u", {"shared": True})
        assert repo.find_by_shared_token("tok-revoked") is not None

    def test_share_token_is_unique(self, pg_conn):
        """CITEXT UNIQUE constraint blocks duplicate share tokens."""
        import sqlalchemy.exc

        repo = _repo(pg_conn)
        repo.create("u", "a1", "published", shared=True, shared_token="dup")
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            repo.create("u", "a2", "published", shared=True, shared_token="DUP")


class TestPart1bFields:
    """Coverage for image, workflow_id, allow_system_prompt_override,
    and FK round-trip via create()."""

    def test_create_with_image_and_override(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            image="https://example.com/avatar.png",
            allow_system_prompt_override=True,
        )
        assert agent["image"] == "https://example.com/avatar.png"
        assert agent["allow_system_prompt_override"] is True

    def test_default_allow_override_is_false(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        assert agent["allow_system_prompt_override"] is False

    def test_extra_source_ids_round_trip(self, pg_conn):
        from docsgpt.storage.db.repositories.sources import SourcesRepository

        sources = SourcesRepository(pg_conn)
        s1 = sources.create("s1", user_id="u")
        s2 = sources.create("s2", user_id="u")
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            source_id=s1["id"],
            extra_source_ids=[s2["id"]],
        )
        # ARRAY(UUID) returns list of UUID objects
        assert [str(x) for x in agent["extra_source_ids"]] == [str(s2["id"])]
        assert str(agent["source_id"]) == str(s1["id"])

    def test_workflow_id_fk(self, pg_conn):
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wf = WorkflowsRepository(pg_conn).create("u", "wf")
        repo = _repo(pg_conn)
        agent = repo.create(
            "u", "a", "draft",
            agent_type="workflow",
            workflow_id=wf["id"],
        )
        assert str(agent["workflow_id"]) == str(wf["id"])

    def test_workflow_id_set_null_on_workflow_delete(self, pg_conn):
        """ON DELETE SET NULL on agents.workflow_id."""
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        wfr = WorkflowsRepository(pg_conn)
        wf = wfr.create("u", "wf")
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft", workflow_id=wf["id"])
        wfr.delete(wf["id"], "u")
        survivor = repo.get(agent["id"], "u")
        assert survivor is not None
        assert survivor["workflow_id"] is None

    def test_update_image_and_override(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        repo.update(agent["id"], "u", {
            "image": "/new.png",
            "allow_system_prompt_override": True,
        })
        fetched = repo.get(agent["id"], "u")
        assert fetched["image"] == "/new.png"
        assert fetched["allow_system_prompt_override"] is True


class TestUpdateLastUsedAt:
    def test_update_last_used_at(self, pg_conn):
        import datetime

        repo = _repo(pg_conn)
        created = repo.create("u", "a", "draft")
        when = datetime.datetime(2026, 4, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        assert repo.update(created["id"], "u", {"last_used_at": when}) is True
        fetched = repo.get(created["id"], "u")
        # ``row_to_dict`` coerces datetimes to ISO strings at the SELECT
        # boundary; round-trip via ``fromisoformat`` to compare values.
        assert datetime.datetime.fromisoformat(fetched["last_used_at"]) == when


def _stamp(conn, agent_id):
    from sqlalchemy import text

    return conn.execute(
        text("SELECT updated_at FROM agents WHERE id = CAST(:id AS uuid)"), {"id": str(agent_id)},
    ).scalar()


def _age(conn, agent_id):
    """Move the agent's ``updated_at`` an hour back, past its trigger.

    ``now()`` is fixed inside the test's transaction, so a bump only shows
    against an older stamp.
    """
    from sqlalchemy import text

    conn.execute(text("ALTER TABLE agents DISABLE TRIGGER agents_set_updated_at"))
    conn.execute(
        text("UPDATE agents SET updated_at = updated_at - interval '1 hour' WHERE id = CAST(:id AS uuid)"),
        {"id": str(agent_id)},
    )
    conn.execute(text("ALTER TABLE agents ENABLE TRIGGER agents_set_updated_at"))
    return _stamp(conn, agent_id)


class TestUpdatedAtTracksContent:
    """``updated_at`` is the builders' stale-write token: only a content edit moves it."""

    @pytest.mark.parametrize(
        "fields",
        [
            {"last_used_at": "2026-04-01T12:00:00+00:00"},
            {"key": "regenerated-key"},
            {"incoming_webhook_token": "hook-token"},
            {"shared": True, "shared_token": "share-token", "shared_metadata": {"shared_by": "u"}},
            {"slug": "first-export"},
        ],
    )
    def test_a_bookkeeping_write_keeps_the_stamp(self, pg_conn, fields):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        stamp = _age(pg_conn, agent["id"])
        assert repo.update(agent["id"], "u", fields) is True
        assert _stamp(pg_conn, agent["id"]) == stamp
        assert repo.update_by_id(agent["id"], fields, expected_updated_at=stamp) is True
        assert _stamp(pg_conn, agent["id"]) == stamp

    def test_a_content_write_moves_the_stamp(self, pg_conn):
        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        stamp = _age(pg_conn, agent["id"])
        assert repo.update(agent["id"], "u", {"name": "b", "last_used_at": None}) is True
        moved = _stamp(pg_conn, agent["id"])
        assert moved > stamp
        stamp = _age(pg_conn, agent["id"])
        assert repo.update_by_id(agent["id"], {"description": "d"}, expected_updated_at=stamp) is True
        assert _stamp(pg_conn, agent["id"]) > stamp

    def test_a_raw_bookkeeping_update_keeps_the_stamp(self, pg_conn):
        """The trigger, not just the repository: any UPDATE of bookkeeping columns alone."""
        from sqlalchemy import text

        agent = _repo(pg_conn).create("u", "a", "draft")
        stamp = _age(pg_conn, agent["id"])
        pg_conn.execute(
            text("UPDATE agents SET last_used_at = now(), key = 'k2' WHERE id = CAST(:id AS uuid)"),
            {"id": str(agent["id"])},
        )
        assert _stamp(pg_conn, agent["id"]) == stamp
        pg_conn.execute(text("UPDATE agents SET chunks = 9 WHERE id = CAST(:id AS uuid)"), {"id": str(agent["id"])})
        assert _stamp(pg_conn, agent["id"]) > stamp

    def test_a_folder_move_keeps_the_stamp(self, pg_conn):
        """Folders are the owner's own filing: moving or unfiling an agent isn't an edit to it."""
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        repo = _repo(pg_conn)
        agent = repo.create("u", "a", "draft")
        folder = AgentFoldersRepository(pg_conn).create("u", "F")
        stamp = _age(pg_conn, agent["id"])
        repo.set_folder(str(agent["id"]), "u", str(folder["id"]))
        assert _stamp(pg_conn, agent["id"]) == stamp
        repo.clear_folder_for_all(str(folder["id"]), "u")
        assert _stamp(pg_conn, agent["id"]) == stamp

    def test_touch_for_workflow_moves_only_the_linked_agents(self, pg_conn):
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        repo = _repo(pg_conn)
        wf = WorkflowsRepository(pg_conn).create("u", "wf")
        linked = repo.create("u", "linked", "draft", workflow_id=wf["id"])
        other = repo.create("u", "other", "draft")
        linked_stamp = _age(pg_conn, linked["id"])
        other_stamp = _age(pg_conn, other["id"])
        repo.touch_for_workflow(str(wf["id"]))
        assert _stamp(pg_conn, linked["id"]) > linked_stamp
        assert _stamp(pg_conn, other["id"]) == other_stamp


class TestListForUser:
    def test_lists_only_own_agents(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("alice", "a1", "draft")
        repo.create("alice", "a2", "active")
        repo.create("bob", "b1", "draft")
        results = repo.list_for_user("alice")
        assert len(results) == 2
        assert all(r["user_id"] == "alice" for r in results)


class TestAgentTypeDefault:
    def test_create_without_type_is_classic(self, pg_conn):
        created = _repo(pg_conn).create("alice", "a", "draft")
        assert created["agent_type"] == "classic"


class TestUpdate:
    def test_updates_name(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft")
        updated = repo.update(created["id"], "user-1", {"name": "new"})
        assert updated is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "new"

    def test_update_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft")
        updated = repo.update(created["id"], "user-other", {"name": "new"})
        assert updated is False
        fetched = repo.get(created["id"], "user-1")
        assert fetched["name"] == "old"

    def test_update_disallowed_field_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        updated = repo.update(created["id"], "user-1", {"id": "bad"})
        assert updated is False

    def test_update_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create(
            "user-1",
            "old",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        updated = repo.update_by_legacy_id(
            "507f1f77bcf86cd799439011",
            "user-1",
            {"name": "new", "last_used_at": None},
        )
        assert updated is True
        fetched = repo.get_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert fetched["name"] == "new"

    def test_update_normalizes_blank_key_to_null(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "old", "draft", key="my-unique-key")
        updated = repo.update(created["id"], "user-1", {"key": ""})
        assert updated is True
        fetched = repo.get(created["id"], "user-1")
        assert fetched["key"] is None


class TestDelete:
    def test_deletes_agent(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None

    def test_delete_wrong_user_returns_false(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create("user-1", "a", "draft")
        deleted = repo.delete(created["id"], "user-other")
        assert deleted is False
        assert repo.get(created["id"], "user-1") is not None

    def test_delete_by_legacy_id(self, pg_conn):
        repo = _repo(pg_conn)
        created = repo.create(
            "user-1",
            "a",
            "draft",
            legacy_mongo_id="507f1f77bcf86cd799439011",
        )
        deleted = repo.delete_by_legacy_id("507f1f77bcf86cd799439011", "user-1")
        assert deleted is True
        assert repo.get(created["id"], "user-1") is None


class TestSetFolder:
    def test_assigns_folder(self, pg_conn):
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft")
        repo.set_folder(agent["id"], "user-1", folder["id"])
        fetched = repo.get(agent["id"], "user-1")
        assert str(fetched["folder_id"]) == str(folder["id"])

    def test_clear_folder(self, pg_conn):
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        agent = repo.create("user-1", "a", "draft", folder_id=folder["id"])
        repo.set_folder(agent["id"], "user-1", None)
        fetched = repo.get(agent["id"], "user-1")
        assert fetched["folder_id"] is None


class TestClearFolderForAll:
    def test_clears_folder_from_all_agents(self, pg_conn):
        from docsgpt.storage.db.repositories.agent_folders import AgentFoldersRepository

        folder_repo = AgentFoldersRepository(pg_conn)
        folder = folder_repo.create("user-1", "f")
        repo = _repo(pg_conn)
        a1 = repo.create("user-1", "a1", "draft", folder_id=folder["id"])
        a2 = repo.create("user-1", "a2", "draft", folder_id=folder["id"])
        repo.clear_folder_for_all(folder["id"], "user-1")
        assert repo.get(a1["id"], "user-1")["folder_id"] is None
        assert repo.get(a2["id"], "user-1")["folder_id"] is None


class TestPromptPresets:
    """``creative`` / ``strict`` have no ``prompts`` row: they live in ``prompt_preset``."""

    def _raw(self, conn, agent_id):
        from sqlalchemy import text

        return conn.execute(
            text("SELECT CAST(prompt_id AS text), prompt_preset FROM agents WHERE id = CAST(:id AS uuid)"),
            {"id": str(agent_id)},
        ).one()

    @pytest.mark.parametrize("preset", ["creative", "strict"])
    def test_create_stores_a_preset_and_reads_it_back_as_prompt_id(self, pg_conn, preset):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", prompt_id=preset)
        assert doc["prompt_id"] == preset
        assert "prompt_preset" not in doc
        assert tuple(self._raw(pg_conn, doc["id"])) == (None, preset)
        assert repo.get(doc["id"], "u")["prompt_id"] == preset

    @pytest.mark.parametrize("value", [None, "", "default"])
    def test_create_with_the_default_stores_nothing(self, pg_conn, value):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", prompt_id=value)
        assert doc["prompt_id"] is None
        assert tuple(self._raw(pg_conn, doc["id"])) == (None, None)

    def test_create_with_a_prompt_row(self, pg_conn):
        from docsgpt.storage.db.repositories.prompts import PromptsRepository

        prompt = PromptsRepository(pg_conn).create("u", "p", "c")
        doc = _repo(pg_conn).create("u", "a", "draft", prompt_id=str(prompt["id"]))
        assert doc["prompt_id"] == str(prompt["id"])
        assert tuple(self._raw(pg_conn, doc["id"])) == (str(prompt["id"]), None)

    def test_update_switches_between_preset_row_and_default(self, pg_conn):
        from docsgpt.storage.db.repositories.prompts import PromptsRepository

        prompt = PromptsRepository(pg_conn).create("u", "p", "c")
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", prompt_id="creative")
        agent_id = str(doc["id"])

        assert repo.update(agent_id, "u", {"prompt_id": "strict"})
        assert repo.get(agent_id, "u")["prompt_id"] == "strict"

        assert repo.update(agent_id, "u", {"prompt_id": str(prompt["id"])})
        assert repo.get(agent_id, "u")["prompt_id"] == str(prompt["id"])
        assert tuple(self._raw(pg_conn, agent_id)) == (str(prompt["id"]), None)

        assert repo.update(agent_id, "u", {"prompt_id": "creative"})
        assert tuple(self._raw(pg_conn, agent_id)) == (None, "creative")

        assert repo.update(agent_id, "u", {"prompt_id": "default"})
        assert repo.get(agent_id, "u")["prompt_id"] is None
        assert tuple(self._raw(pg_conn, agent_id)) == (None, None)

        assert repo.update(agent_id, "u", {"prompt_id": "strict"})
        assert repo.update(agent_id, "u", {"prompt_id": None})
        assert tuple(self._raw(pg_conn, agent_id)) == (None, None)

    def test_update_by_id_stores_a_preset(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft")
        assert repo.update_by_id(str(doc["id"]), {"prompt_id": "strict"})
        assert repo.get_by_id(str(doc["id"]))["prompt_id"] == "strict"

    def test_a_read_row_written_back_is_valid(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create("u", "a", "draft", prompt_id="creative")
        row = repo.get(doc["id"], "u")
        assert repo.update(str(doc["id"]), "u", dict(row))
        assert tuple(self._raw(pg_conn, doc["id"])) == (None, "creative")
        clone = repo.create("u", "copy", "draft", prompt_id=row["prompt_id"])
        assert clone["prompt_id"] == "creative"

    def test_every_read_exposes_the_preset(self, pg_conn):
        repo = _repo(pg_conn)
        doc = repo.create(
            "u", "a", "published", prompt_id="creative", key="k-preset",
            shared=True, shared_token="t-preset", incoming_webhook_token="w-preset", slug="s-preset",
        )
        agent_id = str(doc["id"])
        reads = [
            repo.get(agent_id, "u"),
            repo.get_any(agent_id, "u"),
            repo.get_by_id(agent_id),
            repo.find_by_key("k-preset"),
            repo.find_by_shared_token("t-preset"),
            repo.find_by_webhook_token("w-preset"),
            repo.find_by_slug("u", "s-preset"),
            repo.list_for_user("u")[0],
            repo.list_by_ids([agent_id])[0],
        ]
        for row in reads:
            assert row["prompt_id"] == "creative"
            assert "prompt_preset" not in row

    def test_legacy_reads_and_templates_expose_the_preset(self, pg_conn):
        repo = _repo(pg_conn)
        repo.create("__system__", "tpl", "template", prompt_id="strict", legacy_mongo_id="507f1f77bcf86cd799439099")
        assert repo.get_by_legacy_id("507f1f77bcf86cd799439099")["prompt_id"] == "strict"
        assert next(t for t in repo.list_templates() if t["name"] == "tpl")["prompt_id"] == "strict"

    def test_agent_row_to_dict_for_raw_selects(self, pg_conn):
        from sqlalchemy import text

        from docsgpt.storage.db.repositories.agents import agent_row_to_dict

        doc = _repo(pg_conn).create("u", "a", "draft", prompt_id="strict")
        row = pg_conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"), {"id": str(doc["id"])}
        ).fetchone()
        out = agent_row_to_dict(row)
        assert out["prompt_id"] == "strict"
        assert "prompt_preset" not in out
        assert agent_row_to_dict(None) is None

    def test_the_database_rejects_a_preset_beside_a_prompt_row(self, pg_conn):
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from docsgpt.storage.db.repositories.prompts import PromptsRepository

        prompt = PromptsRepository(pg_conn).create("u", "p", "c")
        doc = _repo(pg_conn).create("u", "a", "draft")
        with pytest.raises(IntegrityError):
            with pg_conn.begin_nested():
                pg_conn.execute(
                    text(
                        "UPDATE agents SET prompt_id = CAST(:p AS uuid), prompt_preset = 'creative' "
                        "WHERE id = CAST(:id AS uuid)"
                    ),
                    {"p": str(prompt["id"]), "id": str(doc["id"])},
                )
        with pytest.raises(IntegrityError):
            with pg_conn.begin_nested():
                pg_conn.execute(
                    text("UPDATE agents SET prompt_preset = 'default' WHERE id = CAST(:id AS uuid)"),
                    {"id": str(doc["id"])},
                )
