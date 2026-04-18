"""Tests for application/seed/seeder.py."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from application.seed.seeder import DatabaseSeeder, SYSTEM_USER_ID


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.seed.seeder.db_session", _yield
    ), patch(
        "application.seed.seeder.db_readonly", _yield
    ):
        yield


class TestDatabaseSeederBasics:
    def test_constructor_takes_optional_legacy_db(self):
        s1 = DatabaseSeeder()
        s2 = DatabaseSeeder(db=MagicMock())
        assert s1.system_user_id == SYSTEM_USER_ID
        assert s2.system_user_id == SYSTEM_USER_ID

    def test_initialize_from_env_returns_instance(self):
        s = DatabaseSeeder.initialize_from_env()
        assert isinstance(s, DatabaseSeeder)


class TestCoerceUuidFk:
    def test_none_returns_none(self):
        assert DatabaseSeeder._coerce_uuid_fk(None) is None

    def test_empty_returns_none(self):
        assert DatabaseSeeder._coerce_uuid_fk("") is None

    def test_default_returns_none(self):
        assert DatabaseSeeder._coerce_uuid_fk("default") is None

    def test_uuid_string_returned_as_is(self):
        assert (
            DatabaseSeeder._coerce_uuid_fk(
                "00000000-0000-0000-0000-000000000001"
            )
            == "00000000-0000-0000-0000-000000000001"
        )


class TestProcessConfig:
    def test_passes_through_plain_values(self):
        seeder = DatabaseSeeder()
        result = seeder._process_config({"x": 1, "y": "foo"})
        assert result == {"x": 1, "y": "foo"}

    def test_resolves_env_var_placeholder(self, monkeypatch):
        monkeypatch.setenv("SEED_TEST_VAR", "the-value")
        seeder = DatabaseSeeder()
        result = seeder._process_config({"key": "${SEED_TEST_VAR}"})
        assert result == {"key": "the-value"}

    def test_missing_env_var_resolves_to_empty(self, monkeypatch):
        monkeypatch.delenv("NOT_SET_VAR", raising=False)
        seeder = DatabaseSeeder()
        result = seeder._process_config({"key": "${NOT_SET_VAR}"})
        assert result == {"key": ""}

    def test_string_not_placeholder_passes_through(self):
        seeder = DatabaseSeeder()
        assert seeder._process_config({"k": "plain-string"}) == {"k": "plain-string"}


class TestIsAlreadySeeded:
    def test_false_when_no_system_agents(self, pg_conn):
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            assert seeder._is_already_seeded() is False

    def test_true_when_system_agents_exist(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            SYSTEM_USER_ID, "TemplateAgent", "template",
        )
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            assert seeder._is_already_seeded() is True


class TestFindSystemAgentByName:
    def test_returns_none_when_not_found(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        got = DatabaseSeeder._find_system_agent_by_name(
            AgentsRepository(pg_conn), "missing"
        )
        assert got is None

    def test_returns_agent_when_name_matches(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        repo = AgentsRepository(pg_conn)
        repo.create(SYSTEM_USER_ID, "Match", "template")
        got = DatabaseSeeder._find_system_agent_by_name(repo, "Match")
        assert got is not None
        assert got["name"] == "Match"


class TestFindSystemSourceByRemoteUrl:
    def test_returns_none_when_repo_lacks_list(self):
        class FakeRepo:
            pass
        assert (
            DatabaseSeeder._find_system_source_by_remote_url(FakeRepo(), "x")
            is None
        )

    def test_returns_none_when_no_match(self, pg_conn):
        from application.storage.db.repositories.sources import SourcesRepository

        got = DatabaseSeeder._find_system_source_by_remote_url(
            SourcesRepository(pg_conn), "https://no-match"
        )
        assert got is None

    def test_matches_dict_remote_data_url(self, pg_conn):
        from application.storage.db.repositories.sources import SourcesRepository

        repo = SourcesRepository(pg_conn)
        repo.create(
            "hello-src",
            user_id=SYSTEM_USER_ID,
            remote_data={"url": "https://example.com/data", "loader": "url"},
        )
        got = DatabaseSeeder._find_system_source_by_remote_url(
            repo, "https://example.com/data"
        )
        assert got is not None


class TestHandlePrompt:
    def test_returns_none_when_no_prompt_field(self, pg_conn):
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            assert seeder._handle_prompt({"name": "agent"}) is None

    def test_returns_none_when_empty_content(self, pg_conn):
        seeder = DatabaseSeeder()
        agent_cfg = {
            "name": "a",
            "prompt": {"name": "p", "content": ""},
        }
        with _patch_db(pg_conn):
            assert seeder._handle_prompt(agent_cfg) is None

    def test_creates_prompt_and_returns_id(self, pg_conn):
        seeder = DatabaseSeeder()
        agent_cfg = {
            "name": "a",
            "prompt": {"name": "test-prompt", "content": "some content"},
        }
        with _patch_db(pg_conn):
            pid = seeder._handle_prompt(agent_cfg)
        assert pid is not None
        from application.storage.db.repositories.prompts import PromptsRepository
        prompts = PromptsRepository(pg_conn).list_for_user(SYSTEM_USER_ID)
        assert any(p["name"] == "test-prompt" for p in prompts)

    def test_handles_exception_returns_none(self, pg_conn):
        seeder = DatabaseSeeder()

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.seed.seeder.db_session", _broken
        ):
            result = seeder._handle_prompt(
                {
                    "name": "a",
                    "prompt": {"name": "p", "content": "c"},
                }
            )
        assert result is None


class TestHandleTools:
    def test_returns_empty_when_no_tools(self, pg_conn):
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            assert seeder._handle_tools({"name": "a"}) == []


class TestHandleSource:
    def test_returns_none_when_no_source(self, pg_conn):
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            assert seeder._handle_source({"name": "a"}) is None

    def test_returns_existing_source_id(self, pg_conn):
        seeder = DatabaseSeeder()
        from application.storage.db.repositories.sources import SourcesRepository

        src = SourcesRepository(pg_conn).create(
            "existing",
            user_id=SYSTEM_USER_ID,
            remote_data={"url": "https://example.com/x", "loader": "url"},
        )
        agent_cfg = {
            "name": "a",
            "source": {"url": "https://example.com/x", "name": "src"},
        }
        with _patch_db(pg_conn):
            got = seeder._handle_source(agent_cfg)
        assert got == src["id"]

    def test_ingest_task_failure_returns_false(self, pg_conn):
        seeder = DatabaseSeeder()

        fake_task = MagicMock()
        fake_task.get.side_effect = RuntimeError("ingestion failed")

        with _patch_db(pg_conn), patch(
            "application.seed.seeder.ingest_remote.delay",
            return_value=fake_task,
        ):
            got = seeder._handle_source(
                {
                    "name": "a",
                    "source": {
                        "url": "https://example.com/new",
                        "name": "s",
                    },
                }
            )
        assert got is False

    def test_successful_ingest_returns_id(self, pg_conn):
        seeder = DatabaseSeeder()

        fake_task = MagicMock()
        fake_task.get.return_value = {"id": "abc-id"}
        fake_task.successful.return_value = True

        with _patch_db(pg_conn), patch(
            "application.seed.seeder.ingest_remote.delay",
            return_value=fake_task,
        ):
            got = seeder._handle_source(
                {
                    "name": "a",
                    "source": {
                        "url": "https://example.com/brand-new",
                        "name": "s",
                    },
                }
            )
        assert got == "abc-id"

    def test_task_result_missing_id_returns_false(self, pg_conn):
        seeder = DatabaseSeeder()

        fake_task = MagicMock()
        fake_task.get.return_value = "just-a-string"
        fake_task.successful.return_value = True

        with _patch_db(pg_conn), patch(
            "application.seed.seeder.ingest_remote.delay",
            return_value=fake_task,
        ):
            got = seeder._handle_source(
                {
                    "name": "a",
                    "source": {
                        "url": "https://example.com/noid",
                        "name": "s",
                    },
                }
            )
        assert got is False


class TestUpsertAgent:
    def test_creates_new_agent(self, pg_conn):
        seeder = DatabaseSeeder()

        agent_cfg = {
            "name": "TemplateA",
            "description": "desc",
            "agent_type": "classic",
            "chunks": "2",
            "retriever": "classic",
        }
        with _patch_db(pg_conn):
            seeder._upsert_agent(agent_cfg, None, [], None)

        from application.storage.db.repositories.agents import AgentsRepository

        rows = AgentsRepository(pg_conn).list_for_user(SYSTEM_USER_ID)
        assert any(r["name"] == "TemplateA" for r in rows)

    def test_updates_existing_agent(self, pg_conn):
        seeder = DatabaseSeeder()

        agent_cfg = {
            "name": "TemplateB",
            "description": "orig",
            "agent_type": "classic",
        }
        with _patch_db(pg_conn):
            seeder._upsert_agent(agent_cfg, None, [], None)
            agent_cfg["description"] = "updated"
            seeder._upsert_agent(agent_cfg, None, [], None)

        from application.storage.db.repositories.agents import AgentsRepository

        rows = AgentsRepository(pg_conn).list_for_user(SYSTEM_USER_ID)
        matching = [r for r in rows if r["name"] == "TemplateB"]
        assert len(matching) == 1
        assert matching[0]["description"] == "updated"


class TestSeedFromConfig:
    def test_no_agents_in_config_warns_and_returns(self, pg_conn):
        seeder = DatabaseSeeder()
        seeder._seed_from_config({})
        # Should not raise; just log a warning

    def test_processes_agents(self, pg_conn):
        seeder = DatabaseSeeder()
        cfg = {
            "agents": [
                {
                    "name": "FromConfigA",
                    "description": "d",
                    "agent_type": "classic",
                },
                {
                    "name": "FromConfigB",
                    "description": "d2",
                    "agent_type": "classic",
                },
            ]
        }
        with _patch_db(pg_conn):
            seeder._seed_from_config(cfg)
        from application.storage.db.repositories.agents import AgentsRepository
        rows = AgentsRepository(pg_conn).list_for_user(SYSTEM_USER_ID)
        names = [r["name"] for r in rows]
        assert "FromConfigA" in names and "FromConfigB" in names


class TestSeedInitialData:
    def test_skips_when_already_seeded(self, pg_conn):
        from application.storage.db.repositories.agents import AgentsRepository

        # Seed one template so _is_already_seeded returns True
        AgentsRepository(pg_conn).create(SYSTEM_USER_ID, "existing", "template")
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn):
            # Should not raise and not do any work
            seeder.seed_initial_data(force=False)

    def test_raises_on_bad_config_path(self, pg_conn):
        seeder = DatabaseSeeder()
        with _patch_db(pg_conn), pytest.raises(Exception):
            seeder.seed_initial_data(
                config_path="/nonexistent-seeder-path.yaml", force=True,
            )
