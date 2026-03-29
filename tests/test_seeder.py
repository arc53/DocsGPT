import os
from unittest.mock import MagicMock, Mock, patch, mock_open

import mongomock
import pytest
from bson import ObjectId
from bson.dbref import DBRef

from application.seed.seeder import DatabaseSeeder


@pytest.fixture
def mock_db():
    client = mongomock.MongoClient()
    return client["test_docsgpt"]


@pytest.fixture
def seeder(mock_db):
    return DatabaseSeeder(mock_db)


# ── __init__ ───────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDatabaseSeederInit:
    def test_collections_set(self, seeder, mock_db):
        assert seeder.db is mock_db
        assert seeder.tools_collection == mock_db["user_tools"]
        assert seeder.sources_collection == mock_db["sources"]
        assert seeder.agents_collection == mock_db["agents"]
        assert seeder.prompts_collection == mock_db["prompts"]
        assert seeder.system_user_id == "system"


# ── _is_already_seeded ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIsAlreadySeeded:
    def test_not_seeded(self, seeder):
        assert seeder._is_already_seeded() is False

    def test_already_seeded(self, seeder, mock_db):
        mock_db["agents"].insert_one({"user": "system", "name": "test"})
        assert seeder._is_already_seeded() is True


# ── _process_config ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestProcessConfig:
    def test_env_var_substitution(self, seeder, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "secret_value")
        result = seeder._process_config({"key": "${MY_SECRET}"})
        assert result["key"] == "secret_value"

    def test_missing_env_var_defaults_empty(self, seeder, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        result = seeder._process_config({"key": "${NONEXISTENT_VAR}"})
        assert result["key"] == ""

    def test_non_env_value_unchanged(self, seeder):
        result = seeder._process_config({"key": "plain_value", "num": 42})
        assert result == {"key": "plain_value", "num": 42}

    def test_partial_env_syntax_unchanged(self, seeder):
        result = seeder._process_config({"key": "${INCOMPLETE"})
        assert result["key"] == "${INCOMPLETE"

    def test_empty_config(self, seeder):
        assert seeder._process_config({}) == {}


# ── _handle_prompt ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandlePrompt:
    def test_no_prompt_returns_none(self, seeder):
        assert seeder._handle_prompt({"name": "agent1"}) is None

    def test_empty_content_returns_none(self, seeder):
        config = {"name": "agent1", "prompt": {"name": "p", "content": ""}}
        assert seeder._handle_prompt(config) is None

    def test_creates_prompt(self, seeder, mock_db):
        config = {
            "name": "agent1",
            "prompt": {"name": "My Prompt", "content": "You are helpful."},
        }
        result = seeder._handle_prompt(config)
        assert result is not None
        doc = mock_db["prompts"].find_one({"name": "My Prompt"})
        assert doc is not None
        assert doc["content"] == "You are helpful."
        assert doc["user"] == "system"

    def test_duplicate_prompt_returns_existing(self, seeder, mock_db):
        config = {
            "name": "agent1",
            "prompt": {"name": "Dup Prompt", "content": "content"},
        }
        id1 = seeder._handle_prompt(config)
        id2 = seeder._handle_prompt(config)
        assert id1 == id2
        assert mock_db["prompts"].count_documents({"name": "Dup Prompt"}) == 1

    def test_default_prompt_name(self, seeder, mock_db):
        config = {"name": "agent1", "prompt": {"content": "hello"}}
        seeder._handle_prompt(config)
        doc = mock_db["prompts"].find_one({"name": "agent1 Prompt"})
        assert doc is not None

    def test_exception_returns_none(self, seeder):
        with patch.object(
            seeder.prompts_collection, "find_one", side_effect=RuntimeError("db error")
        ):
            config = {
                "name": "agent1",
                "prompt": {"name": "p", "content": "c"},
            }
            assert seeder._handle_prompt(config) is None


# ── _handle_tools ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleTools:
    def test_no_tools_returns_empty(self, seeder):
        assert seeder._handle_tools({"name": "agent1"}) == []

    @patch("application.seed.seeder.tool_manager")
    def test_creates_tool(self, mock_tm, seeder, mock_db):
        mock_tool = MagicMock()
        mock_tool.get_actions_metadata.return_value = [{"name": "act1"}]
        mock_tm.tools = {"my_tool": mock_tool}

        config = {
            "name": "agent1",
            "tools": [{"name": "my_tool", "description": "desc"}],
        }
        ids = seeder._handle_tools(config)
        assert len(ids) == 1
        doc = mock_db["user_tools"].find_one({"name": "my_tool"})
        assert doc is not None
        assert doc["user"] == "system"

    @patch("application.seed.seeder.tool_manager")
    def test_duplicate_tool_returns_existing(self, mock_tm, seeder, mock_db):
        mock_tool = MagicMock()
        mock_tool.get_actions_metadata.return_value = []
        mock_tm.tools = {"my_tool": mock_tool}

        config = {
            "name": "agent1",
            "tools": [{"name": "my_tool"}],
        }
        ids1 = seeder._handle_tools(config)
        ids2 = seeder._handle_tools(config)
        assert ids1 == ids2
        assert mock_db["user_tools"].count_documents({"name": "my_tool"}) == 1

    def test_tool_exception_continues(self, seeder):
        config = {
            "name": "agent1",
            "tools": [{"name": "broken_tool"}],
        }
        # tool_manager.tools will KeyError on "broken_tool"
        ids = seeder._handle_tools(config)
        assert ids == []

    @patch("application.seed.seeder.tool_manager")
    def test_tool_config_env_expansion(self, mock_tm, seeder, monkeypatch):
        monkeypatch.setenv("TOOL_KEY", "expanded_val")
        mock_tool = MagicMock()
        mock_tool.get_actions_metadata.return_value = []
        mock_tm.tools = {"my_tool": mock_tool}

        config = {
            "name": "agent1",
            "tools": [{"name": "my_tool", "config": {"api_key": "${TOOL_KEY}"}}],
        }
        seeder._handle_tools(config)
        doc = seeder.tools_collection.find_one({"name": "my_tool"})
        assert doc["config"]["api_key"] == "expanded_val"


# ── _handle_source ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleSource:
    def test_no_source_returns_none(self, seeder):
        assert seeder._handle_source({"name": "a"}) is None

    def test_existing_source_returns_id(self, seeder, mock_db):
        inserted = mock_db["sources"].insert_one(
            {"user": "system", "remote_data": "http://example.com"}
        )
        config = {
            "name": "a",
            "source": {"url": "http://example.com", "name": "src"},
        }
        result = seeder._handle_source(config)
        assert result == inserted.inserted_id

    @patch("application.seed.seeder.ingest_remote")
    def test_new_source_ingestion(self, mock_ingest, seeder):
        mock_task = MagicMock()
        mock_task.get.return_value = {"id": "new_source_id"}
        mock_task.successful.return_value = True
        mock_ingest.delay.return_value = mock_task

        config = {
            "name": "a",
            "source": {"url": "http://new.com", "name": "new_src", "loader": "web"},
        }
        result = seeder._handle_source(config)
        assert result == "new_source_id"
        mock_ingest.delay.assert_called_once_with(
            source_data="http://new.com",
            job_name="new_src",
            user="system",
            loader="web",
        )

    @patch("application.seed.seeder.ingest_remote")
    def test_source_ingestion_failure_returns_false(self, mock_ingest, seeder):
        mock_task = MagicMock()
        mock_task.get.side_effect = RuntimeError("timeout")
        mock_ingest.delay.return_value = mock_task

        config = {
            "name": "a",
            "source": {"url": "http://fail.com", "name": "fail_src"},
        }
        result = seeder._handle_source(config)
        assert result is False

    @patch("application.seed.seeder.ingest_remote")
    def test_source_missing_id_returns_false(self, mock_ingest, seeder):
        mock_task = MagicMock()
        mock_task.get.return_value = {"no_id_key": True}
        mock_task.successful.return_value = True
        mock_ingest.delay.return_value = mock_task

        config = {
            "name": "a",
            "source": {"url": "http://bad.com", "name": "bad_src"},
        }
        result = seeder._handle_source(config)
        assert result is False

    @patch("application.seed.seeder.ingest_remote")
    def test_default_loader(self, mock_ingest, seeder):
        mock_task = MagicMock()
        mock_task.get.return_value = {"id": "sid"}
        mock_task.successful.return_value = True
        mock_ingest.delay.return_value = mock_task

        config = {
            "name": "a",
            "source": {"url": "http://x.com", "name": "s"},
        }
        seeder._handle_source(config)
        call_kwargs = mock_ingest.delay.call_args[1]
        assert call_kwargs["loader"] == "url"


# ── seed_initial_data ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSeedInitialData:
    def test_already_seeded_skips(self, seeder, mock_db):
        mock_db["agents"].insert_one({"user": "system", "name": "existing"})
        with patch.object(seeder, "_seed_from_config") as mock_seed:
            seeder.seed_initial_data()
            mock_seed.assert_not_called()

    def test_force_reseeds(self, seeder, mock_db):
        mock_db["agents"].insert_one({"user": "system", "name": "existing"})
        yaml_content = "agents: []"
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch.object(seeder, "_seed_from_config") as mock_seed:
                seeder.seed_initial_data(force=True)
                mock_seed.assert_called_once()

    def test_config_file_not_found_raises(self, seeder):
        with pytest.raises(Exception):
            seeder.seed_initial_data(config_path="/nonexistent/path.yaml")

    def test_custom_config_path(self, seeder):
        yaml_content = "agents:\n  - name: test_agent"
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch.object(seeder, "_seed_from_config") as mock_seed:
                seeder.seed_initial_data(config_path="/custom/path.yaml")
                mock_seed.assert_called_once()


# ── _seed_from_config ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSeedFromConfig:
    def test_no_agents_in_config(self, seeder):
        seeder._seed_from_config({})
        assert seeder.agents_collection.count_documents({}) == 0

    def test_empty_agents_list(self, seeder):
        seeder._seed_from_config({"agents": []})
        assert seeder.agents_collection.count_documents({}) == 0

    @patch.object(DatabaseSeeder, "_handle_source", return_value=None)
    @patch.object(DatabaseSeeder, "_handle_tools", return_value=[])
    @patch.object(DatabaseSeeder, "_handle_prompt", return_value=None)
    def test_creates_agent(self, mock_prompt, mock_tools, mock_source, seeder, mock_db):
        config = {
            "agents": [
                {
                    "name": "TestAgent",
                    "description": "A test agent",
                    "agent_type": "classic",
                }
            ]
        }
        seeder._seed_from_config(config)
        agent = mock_db["agents"].find_one({"name": "TestAgent"})
        assert agent is not None
        assert agent["user"] == "system"
        assert agent["agent_type"] == "classic"
        assert agent["status"] == "template"

    @patch.object(DatabaseSeeder, "_handle_source", return_value=None)
    @patch.object(DatabaseSeeder, "_handle_tools", return_value=[])
    @patch.object(DatabaseSeeder, "_handle_prompt", return_value=None)
    def test_updates_existing_agent(self, mock_prompt, mock_tools, mock_source, seeder, mock_db):
        mock_db["agents"].insert_one(
            {"user": "system", "name": "TestAgent", "description": "old"}
        )
        config = {
            "agents": [
                {
                    "name": "TestAgent",
                    "description": "updated",
                    "agent_type": "classic",
                }
            ]
        }
        seeder._seed_from_config(config)
        assert mock_db["agents"].count_documents({"name": "TestAgent"}) == 1
        agent = mock_db["agents"].find_one({"name": "TestAgent"})
        assert agent["description"] == "updated"

    @patch.object(DatabaseSeeder, "_handle_source", return_value=False)
    def test_source_failure_skips_agent(self, mock_source, seeder, mock_db):
        config = {
            "agents": [
                {
                    "name": "SkippedAgent",
                    "description": "skip",
                    "agent_type": "classic",
                }
            ]
        }
        seeder._seed_from_config(config)
        assert mock_db["agents"].count_documents({"name": "SkippedAgent"}) == 0

    @patch.object(DatabaseSeeder, "_handle_source", side_effect=KeyError("name"))
    def test_agent_exception_continues(self, mock_source, seeder, mock_db):
        config = {
            "agents": [
                {"name": "Bad", "description": "x", "agent_type": "y"},
                {"name": "Good", "description": "x", "agent_type": "y"},
            ]
        }
        with patch.object(seeder, "_handle_tools", return_value=[]):
            with patch.object(seeder, "_handle_prompt", return_value=None):
                seeder._seed_from_config(config)
        # Both agents should be attempted; first errors, second might too
        # Main assertion: no unhandled exception

    @patch.object(DatabaseSeeder, "_handle_source", return_value=None)
    @patch.object(DatabaseSeeder, "_handle_tools")
    @patch.object(DatabaseSeeder, "_handle_prompt", return_value="prompt_id_123")
    def test_agent_with_source_and_tools(self, mock_prompt, mock_tools, mock_source, seeder, mock_db):
        tool_id = ObjectId()
        mock_tools.return_value = [tool_id]

        source_id = ObjectId()
        mock_source.return_value = source_id

        config = {
            "agents": [
                {
                    "name": "FullAgent",
                    "description": "full",
                    "agent_type": "classic",
                    "chunks": "5",
                    "retriever": "classic",
                    "image": "img.png",
                }
            ]
        }
        seeder._seed_from_config(config)
        agent = mock_db["agents"].find_one({"name": "FullAgent"})
        assert agent is not None
        assert agent["prompt_id"] == "prompt_id_123"
        assert str(tool_id) in agent["tools"]
        assert agent["chunks"] == "5"
        assert agent["image"] == "img.png"


# ── initialize_from_env ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestInitializeFromEnv:
    @patch("application.seed.seeder.MongoClient")
    def test_creates_seeder_from_env(self, mock_client_cls, monkeypatch):
        monkeypatch.setenv("MONGO_URI", "mongodb://test:27017")
        monkeypatch.setenv("MONGO_DB_NAME", "testdb")

        mock_db = mongomock.MongoClient()["testdb"]
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_client_cls.return_value = mock_client

        seeder = DatabaseSeeder.initialize_from_env()
        mock_client_cls.assert_called_once_with("mongodb://test:27017")
        assert isinstance(seeder, DatabaseSeeder)

    @patch("application.seed.seeder.MongoClient")
    def test_default_env_values(self, mock_client_cls, monkeypatch):
        monkeypatch.delenv("MONGO_URI", raising=False)
        monkeypatch.delenv("MONGO_DB_NAME", raising=False)

        mock_db = mongomock.MongoClient()["docsgpt"]
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_client_cls.return_value = mock_client

        DatabaseSeeder.initialize_from_env()
        mock_client_cls.assert_called_once_with("mongodb://localhost:27017")


# ── seed CLI commands ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSeedCommands:
    @patch("application.seed.commands.DatabaseSeeder")
    @patch("application.seed.commands.MongoDB")
    @patch("application.seed.commands.settings")
    def test_init_command(self, mock_settings, mock_mongodb, mock_seeder_cls):
        from click.testing import CliRunner
        from application.seed.commands import seed

        mock_settings.MONGO_DB_NAME = "testdb"
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value="mock_db")
        mock_mongodb.get_client.return_value = mock_client

        mock_seeder = MagicMock()
        mock_seeder_cls.return_value = mock_seeder

        runner = CliRunner()
        result = runner.invoke(seed, ["init"])
        assert result.exit_code == 0
        mock_seeder.seed_initial_data.assert_called_once_with(force=False)

    @patch("application.seed.commands.DatabaseSeeder")
    @patch("application.seed.commands.MongoDB")
    @patch("application.seed.commands.settings")
    def test_init_command_with_force(self, mock_settings, mock_mongodb, mock_seeder_cls):
        from click.testing import CliRunner
        from application.seed.commands import seed

        mock_settings.MONGO_DB_NAME = "testdb"
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value="mock_db")
        mock_mongodb.get_client.return_value = mock_client

        mock_seeder = MagicMock()
        mock_seeder_cls.return_value = mock_seeder

        runner = CliRunner()
        result = runner.invoke(seed, ["init", "--force"])
        assert result.exit_code == 0
        mock_seeder.seed_initial_data.assert_called_once_with(force=True)
