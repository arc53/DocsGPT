"""
Main user API routes - registers all namespace modules.
"""

from flask import Blueprint

from application.api import api
from application.api.admin import admin_ns
from .agents import (
    agents_folders_ns,
    agents_ns,
    agents_portability_ns,
    agents_sharing_ns,
    agents_webhooks_ns,
)
from .analytics import analytics_ns
from .attachments import attachments_ns
from .conversations import conversations_ns
from .me import me_ns
from .models import models_ns
from .prompts import prompts_ns
from .schedules import schedules_ns
from .sharing import sharing_ns
from .sources import sources_chunks_ns, sources_ns, sources_upload_ns
from .teams import teams_ns
from .tools import tools_mcp_ns, tools_ns
from .workflows import workflows_ns


user = Blueprint("user", __name__)

# Analytics
api.add_namespace(analytics_ns)

# Attachments
api.add_namespace(attachments_ns)

# Conversations
api.add_namespace(conversations_ns)

# Current user (identity + roles)
api.add_namespace(me_ns)

# Models
api.add_namespace(models_ns)

# Agents (main, sharing, webhooks, folders, import/export)
api.add_namespace(agents_ns)
api.add_namespace(agents_sharing_ns)
api.add_namespace(agents_webhooks_ns)
api.add_namespace(agents_folders_ns)
api.add_namespace(agents_portability_ns)

# Prompts
api.add_namespace(prompts_ns)

# Schedules
api.add_namespace(schedules_ns)

# Sharing
api.add_namespace(sharing_ns)

# Sources (main, chunks, upload)
api.add_namespace(sources_ns)
api.add_namespace(sources_chunks_ns)
api.add_namespace(sources_upload_ns)

# Teams (CRUD, membership, resource-sharing grants)
api.add_namespace(teams_ns)

# Tools (main, MCP)
api.add_namespace(tools_ns)
api.add_namespace(tools_mcp_ns)

# Workflows
api.add_namespace(workflows_ns)

# Admin (admin-gated management endpoints). Registered here, in this
# import-cached module, rather than in app.py's body so a re-import of
# application.app (e.g. coverage tests that reload the module) doesn't re-fire
# add_namespace against the already-initialized Api.
api.add_namespace(admin_ns)
