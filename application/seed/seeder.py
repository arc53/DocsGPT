"""Database seeder — Postgres-native.

Post-Part-2 cutover: writes template prompts/tools/agents/sources directly
into Postgres via the repository layer. No MongoDB dependencies.

The seeder is invoked by the ``python -m application.seed.commands init``
CLI (not at Flask app startup). All template rows are owned by the
sentinel user id ``__system__`` — kept in sync with the migration
backfill/cleanup-trigger sentinel so template ownership is predictable.
"""

import logging
import os
from typing import Dict, List, Optional

import yaml
from dotenv import load_dotenv

from application.agents.tools.tool_manager import ToolManager
from application.api.user.tasks import ingest_remote
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.prompts import PromptsRepository
from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly, db_session

load_dotenv()
tool_config = {}
tool_manager = ToolManager(config=tool_config)


# Sentinel user id for template rows (agents/prompts/sources/tools).
# Kept in sync with the Postgres backfill / cleanup-trigger sentinel so
# template ownership is predictable across the cutover.
SYSTEM_USER_ID = "__system__"


class DatabaseSeeder:
    """Postgres-backed seeder.

    The constructor accepts an optional positional argument for back
    compatibility with legacy callers that used to pass a Mongo ``db``
    handle. The value is ignored — all persistence goes through the
    Postgres repositories.
    """

    def __init__(self, db=None):
        self._legacy_db = db  # unused; retained for call-site compatibility
        self.system_user_id = SYSTEM_USER_ID
        self.logger = logging.getLogger(__name__)

    def seed_initial_data(self, config_path: str = None, force=False):
        """Main entry point for seeding all initial data."""
        if not force and self._is_already_seeded():
            self.logger.info("Database already seeded. Use force=True to reseed.")
            return
        config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config", "premade_agents.yaml"
        )

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
                self._seed_from_config(config)
        except Exception as e:
            self.logger.error(f"Failed to load seeding config: {str(e)}")
            raise

    def _seed_from_config(self, config: Dict):
        """Seed all data from configuration."""
        self.logger.info("Starting seeding...")

        if not config.get("agents"):
            self.logger.warning("No agents found in config")
            return

        for agent_config in config["agents"]:
            try:
                self.logger.info(f"Processing agent: {agent_config['name']}")

                # 1. Handle Source
                source_result = self._handle_source(agent_config)
                if source_result is False:
                    self.logger.error(
                        f"Skipping agent {agent_config['name']} due to source ingestion failure"
                    )
                    continue
                source_id = source_result

                # 2. Handle Tools
                tool_ids = self._handle_tools(agent_config)
                if len(tool_ids) == 0:
                    self.logger.warning(
                        f"No valid tools for agent {agent_config['name']}"
                    )

                # 3. Handle Prompt
                prompt_id = self._handle_prompt(agent_config)

                # 4. Create or update Agent
                self._upsert_agent(agent_config, source_id, tool_ids, prompt_id)

            except Exception as e:
                self.logger.error(
                    f"Error processing agent {agent_config['name']}: {str(e)}"
                )
                continue
        self.logger.info("Database seeding completed")

    def _upsert_agent(
        self,
        agent_config: Dict,
        source_id: Optional[str],
        tool_ids: List[str],
        prompt_id: Optional[str],
    ) -> None:
        """Create or update a template agent owned by ``__system__``."""
        name = agent_config["name"]
        agent_fields = {
            "description": agent_config["description"],
            "image": agent_config.get("image", ""),
            "tools": [str(tid) for tid in tool_ids],
            "agent_type": agent_config["agent_type"],
            "prompt_id": prompt_id or agent_config.get("prompt_id", "default"),
            "chunks": agent_config.get("chunks", "0"),
            "retriever": agent_config.get("retriever", ""),
        }
        if source_id:
            agent_fields["source_id"] = str(source_id)

        with db_session() as conn:
            repo = AgentsRepository(conn)
            existing = self._find_system_agent_by_name(repo, name)
            if existing:
                self.logger.info(f"Updating existing agent: {name}")
                repo.update(str(existing["id"]), self.system_user_id, agent_fields)
                self.logger.info(f"Successfully updated agent: {name} (ID: {existing['id']})")
            else:
                self.logger.info(f"Creating new agent: {name}")
                created = repo.create(
                    user_id=self.system_user_id,
                    name=name,
                    status="template",
                    **agent_fields,
                )
                self.logger.info(
                    f"Successfully created agent: {name} (ID: {created.get('id')})"
                )

    @staticmethod
    def _find_system_agent_by_name(repo: AgentsRepository, name: str) -> Optional[dict]:
        """Find a system-owned agent by name among the template rows."""
        for row in repo.list_for_user(SYSTEM_USER_ID):
            if row.get("name") == name:
                return row
        return None

    def _handle_source(self, agent_config: Dict):
        """Handle source ingestion and return a source id (UUID string) or ``None``/``False``."""
        if not agent_config.get("source"):
            self.logger.info(
                "No source provided for agent - will create agent without source"
            )
            return None
        source_config = agent_config["source"]
        self.logger.info(f"Ingesting source: {source_config['url']}")

        try:
            with db_readonly() as conn:
                existing = self._find_system_source_by_remote_url(
                    SourcesRepository(conn), source_config["url"]
                )
            if existing:
                self.logger.info(f"Source already exists: {existing['id']}")
                return existing["id"]

            # Ingest new source using worker
            task = ingest_remote.delay(
                source_data=source_config["url"],
                job_name=source_config["name"],
                user=self.system_user_id,
                loader=source_config.get("loader", "url"),
            )

            result = task.get(timeout=300)

            if not task.successful():
                raise Exception(f"Source ingestion failed: {result}")
            source_id = None
            if isinstance(result, dict) and "id" in result:
                source_id = result["id"]
            else:
                raise Exception(f"Source ingestion result missing 'id': {result}")
            self.logger.info(f"Source ingested successfully: {source_id}")
            return source_id
        except Exception as e:
            self.logger.error(f"Failed to ingest source: {str(e)}")
            return False

    @staticmethod
    def _find_system_source_by_remote_url(
        repo: SourcesRepository, url: str
    ) -> Optional[dict]:
        """Scan system-owned sources for a row whose remote_data matches ``url``."""
        # TODO(migration-postgres): push this into SourcesRepository once a
        # remote_data search helper exists; today we keep the scan here to
        # stay within this slice's boundaries.
        try:
            rows = repo.list_for_user(SYSTEM_USER_ID)  # type: ignore[attr-defined]
        except AttributeError:
            return None
        for row in rows:
            remote = row.get("remote_data")
            if remote == url:
                return row
            if isinstance(remote, dict) and remote.get("url") == url:
                return row
        return None

    def _handle_tools(self, agent_config: Dict) -> List[str]:
        """Handle tool creation and return list of tool ids (UUID strings)."""
        tool_ids: List[str] = []
        if not agent_config.get("tools"):
            return tool_ids
        for tool_config in agent_config["tools"]:
            try:
                tool_name = tool_config["name"]
                processed_config = self._process_config(tool_config.get("config", {}))
                self.logger.info(f"Processing tool: {tool_name}")

                with db_session() as conn:
                    repo = UserToolsRepository(conn)
                    existing = self._find_system_tool(
                        repo, tool_name, processed_config
                    )
                    if existing:
                        self.logger.info(f"Tool already exists: {existing['id']}")
                        tool_ids.append(existing["id"])
                        continue
                    created = repo.create(
                        user_id=self.system_user_id,
                        name=tool_name,
                        display_name=tool_config.get("display_name", tool_name),
                        description=tool_config.get("description", ""),
                        actions=tool_manager.tools[tool_name].get_actions_metadata(),
                        config=processed_config,
                        status=True,
                    )
                    tool_ids.append(created["id"])
                    self.logger.info(f"Created new tool: {created['id']}")
            except Exception as e:
                self.logger.error(f"Failed to process tool {tool_name}: {str(e)}")
                continue
        return tool_ids

    @staticmethod
    def _find_system_tool(
        repo: UserToolsRepository, name: str, config: dict
    ) -> Optional[dict]:
        """Locate a system-owned tool by (name, config) among existing rows."""
        existing = repo.find_by_user_and_name(SYSTEM_USER_ID, name)
        if existing and existing.get("config") == config:
            return existing
        return None

    def _handle_prompt(self, agent_config: Dict) -> Optional[str]:
        """Handle prompt creation and return prompt id (UUID string)."""
        if not agent_config.get("prompt"):
            return None

        prompt_config = agent_config["prompt"]
        prompt_name = prompt_config.get("name", f"{agent_config['name']} Prompt")
        prompt_content = prompt_config.get("content", "")

        if not prompt_content:
            self.logger.warning(
                f"No prompt content provided for agent {agent_config['name']}"
            )
            return None

        self.logger.info(f"Processing prompt: {prompt_name}")

        try:
            with db_session() as conn:
                repo = PromptsRepository(conn)
                row = repo.find_or_create(
                    self.system_user_id, prompt_name, prompt_content
                )
                prompt_id = str(row["id"])
                self.logger.info(f"Prompt ready: {prompt_id}")
                return prompt_id
        except Exception as e:
            self.logger.error(f"Failed to process prompt {prompt_name}: {str(e)}")
            return None

    def _process_config(self, config: Dict) -> Dict:
        """Process config values to replace environment variables."""
        processed = {}
        for key, value in config.items():
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                env_var = value[2:-1]
                processed[key] = os.getenv(env_var, "")
            else:
                processed[key] = value
        return processed

    def _is_already_seeded(self) -> bool:
        """Check if premade (system-owned) agents already exist in Postgres."""
        with db_readonly() as conn:
            repo = AgentsRepository(conn)
            return len(repo.list_for_user(SYSTEM_USER_ID)) > 0

    @classmethod
    def initialize_from_env(cls, worker=None):
        """Factory method to create seeder from environment.

        Retained for back compatibility with existing call sites. The
        Postgres connection is resolved lazily via the repository layer
        (``application.storage.db.engine``), so no explicit wiring is
        required here.
        """
        return cls()
