"""
Main user API routes - registers all namespace modules.
"""

from flask import Blueprint

from application.api import api
from .agents import agents_ns, agents_sharing_ns, agents_webhooks_ns, agents_folders_ns
from .analytics import analytics_ns
from .attachments import attachments_ns
from .conversations import conversations_ns
from .models import models_ns
from .prompts import prompts_ns
from .sharing import sharing_ns
from .sources import sources_chunks_ns, sources_ns, sources_upload_ns
from .tools import tools_mcp_ns, tools_ns
from .workflows import workflows_ns


user = Blueprint("user", __name__)

# Analytics
api.add_namespace(analytics_ns)

# Attachments
api.add_namespace(attachments_ns)

# Conversations
api.add_namespace(conversations_ns)

# Models
api.add_namespace(models_ns)

# Agents (main, sharing, webhooks, folders)
api.add_namespace(agents_ns)
api.add_namespace(agents_sharing_ns)
api.add_namespace(agents_webhooks_ns)
api.add_namespace(agents_folders_ns)

# Prompts
api.add_namespace(prompts_ns)

# Sharing
api.add_namespace(sharing_ns)

# Sources (main, chunks, upload)
api.add_namespace(sources_ns)
api.add_namespace(sources_chunks_ns)
api.add_namespace(sources_upload_ns)

# Tools (main, MCP)
api.add_namespace(tools_ns)
api.add_namespace(tools_mcp_ns)

# Workflows
api.add_namespace(workflows_ns)
