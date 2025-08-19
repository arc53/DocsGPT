import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Union

import yaml
from bson import ObjectId
from bson.dbref import DBRef

from dotenv import load_dotenv
from pymongo import MongoClient

from application.agents.tools.tool_manager import ToolManager
from application.api.user.tasks import ingest_remote

load_dotenv()
tool_config = {}
tool_manager = ToolManager(config=tool_config)


class DatabaseSeeder:
    def __init__(self, db):
        self.db = db
        self.tools_collection = self.db["user_tools"]
        self.sources_collection = self.db["sources"]
        self.agents_collection = self.db["agents"]
        self.prompts_collection = self.db["prompts"]
        self.system_user_id = "system"
        self.logger = logging.getLogger(__name__)

    def seed_initial_data(self, config_path: str = None, force=False):
        """Main entry point for seeding all initial data"""
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
        """Seed all data from configuration"""
        self.logger.info("🌱 Starting seeding...")

        if not config.get("agents"):
            self.logger.warning("No agents found in config")
            return
        used_tool_ids = set()

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
                used_tool_ids.update(tool_ids)

                # 3. Handle Prompt

                prompt_id = self._handle_prompt(agent_config)

                # 4. Create Agent

                agent_data = {
                    "user": self.system_user_id,
                    "name": agent_config["name"],
                    "description": agent_config["description"],
                    "image": agent_config.get("image", ""),
                    "source": (
                        DBRef("sources", ObjectId(source_id)) if source_id else ""
                    ),
                    "tools": [str(tid) for tid in tool_ids],
                    "agent_type": agent_config["agent_type"],
                    "prompt_id": prompt_id or agent_config.get("prompt_id", "default"),
                    "chunks": agent_config.get("chunks", "0"),
                    "retriever": agent_config.get("retriever", ""),
                    "status": "template",
                    "createdAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc),
                }

                existing = self.agents_collection.find_one(
                    {"user": self.system_user_id, "name": agent_config["name"]}
                )
                if existing:
                    self.logger.info(f"Updating existing agent: {agent_config['name']}")
                    self.agents_collection.update_one(
                        {"_id": existing["_id"]}, {"$set": agent_data}
                    )
                    agent_id = existing["_id"]
                else:
                    self.logger.info(f"Creating new agent: {agent_config['name']}")
                    result = self.agents_collection.insert_one(agent_data)
                    agent_id = result.inserted_id
                self.logger.info(
                    f"Successfully processed agent: {agent_config['name']} (ID: {agent_id})"
                )
            except Exception as e:
                self.logger.error(
                    f"Error processing agent {agent_config['name']}: {str(e)}"
                )
                continue
        self.logger.info("✅ Database seeding completed")

    def _handle_source(self, agent_config: Dict) -> Union[ObjectId, None, bool]:
        """Handle source ingestion and return source ID"""
        if not agent_config.get("source"):
            self.logger.info(
                "No source provided for agent - will create agent without source"
            )
            return None
        source_config = agent_config["source"]
        self.logger.info(f"Ingesting source: {source_config['url']}")

        try:
            existing = self.sources_collection.find_one(
                {"user": self.system_user_id, "remote_data": source_config["url"]}
            )
            if existing:
                self.logger.info(f"Source already exists: {existing['_id']}")
                return existing["_id"]
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

    def _handle_tools(self, agent_config: Dict) -> List[ObjectId]:
        """Handle tool creation and return list of tool IDs"""
        tool_ids = []
        if not agent_config.get("tools"):
            return tool_ids
        for tool_config in agent_config["tools"]:
            try:
                tool_name = tool_config["name"]
                processed_config = self._process_config(tool_config.get("config", {}))
                self.logger.info(f"Processing tool: {tool_name}")

                existing = self.tools_collection.find_one(
                    {
                        "user": self.system_user_id,
                        "name": tool_name,
                        "config": processed_config,
                    }
                )
                if existing:
                    self.logger.info(f"Tool already exists: {existing['_id']}")
                    tool_ids.append(existing["_id"])
                    continue
                tool_data = {
                    "user": self.system_user_id,
                    "name": tool_name,
                    "displayName": tool_config.get("display_name", tool_name),
                    "description": tool_config.get("description", ""),
                    "actions": tool_manager.tools[tool_name].get_actions_metadata(),
                    "config": processed_config,
                    "status": True,
                }

                result = self.tools_collection.insert_one(tool_data)
                tool_ids.append(result.inserted_id)
                self.logger.info(f"Created new tool: {result.inserted_id}")
            except Exception as e:
                self.logger.error(f"Failed to process tool {tool_name}: {str(e)}")
                continue
        return tool_ids

    def _handle_prompt(self, agent_config: Dict) -> Optional[str]:
        """Handle prompt creation and return prompt ID"""
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
            existing = self.prompts_collection.find_one(
                {
                    "user": self.system_user_id,
                    "name": prompt_name,
                    "content": prompt_content,
                }
            )
            if existing:
                self.logger.info(f"Prompt already exists: {existing['_id']}")
                return str(existing["_id"])

            prompt_data = {
                "name": prompt_name,
                "content": prompt_content,
                "user": self.system_user_id,
            }

            result = self.prompts_collection.insert_one(prompt_data)
            prompt_id = str(result.inserted_id)
            self.logger.info(f"Created new prompt: {prompt_id}")
            return prompt_id

        except Exception as e:
            self.logger.error(f"Failed to process prompt {prompt_name}: {str(e)}")
            return None

    def _process_config(self, config: Dict) -> Dict:
        """Process config values to replace environment variables"""
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
        """Check if premade agents already exist"""
        return self.agents_collection.count_documents({"user": self.system_user_id}) > 0

    @classmethod
    def initialize_from_env(cls, worker=None):
        """Factory method to create seeder from environment"""
        mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGO_DB_NAME", "docsgpt")
        client = MongoClient(mongo_uri)
        db = client[db_name]
        return cls(db)
