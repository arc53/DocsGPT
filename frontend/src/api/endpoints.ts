const endpoints = {
  USER: {
    CONFIG: '/api/config',
    ME: '/api/user/me',
    NEW_TOKEN: '/api/generate_token',
    OIDC_LOGIN: '/api/auth/oidc/login',
    OIDC_TOKEN: '/api/auth/oidc/token',
    OIDC_REFRESH: '/api/auth/oidc/refresh',
    OIDC_LOGOUT: '/api/auth/oidc/logout',
    MODELS: '/api/models',
    DOCS: '/api/sources',
    DOCS_PAGINATED: '/api/sources/paginated',
    API_KEYS: '/api/get_api_keys',
    CREATE_API_KEY: '/api/create_api_key',
    DELETE_API_KEY: '/api/delete_api_key',
    AGENT: (id: string) => `/api/get_agent?id=${id}`,
    AGENTS: '/api/get_agents',
    CREATE_AGENT: '/api/create_agent',
    UPDATE_AGENT: (agent_id: string) => `/api/update_agent/${agent_id}`,
    DELETE_AGENT: (id: string) => `/api/delete_agent?id=${id}`,
    PINNED_AGENTS: '/api/pinned_agents',
    TOGGLE_PIN_AGENT: (id: string) => `/api/pin_agent?id=${id}`,
    SHARED_AGENT: (id: string) => `/api/shared_agent?token=${id}`,
    SHARED_AGENTS: '/api/shared_agents',
    SHARE_AGENT: `/api/share_agent`,
    REMOVE_SHARED_AGENT: (id: string) => `/api/remove_shared_agent?id=${id}`,
    TEMPLATE_AGENTS: '/api/template_agents',
    ADOPT_AGENT: (id: string) => `/api/adopt_agent?id=${id}`,
    AGENT_WEBHOOK: (id: string) => `/api/agent_webhook?id=${id}`,
    EXPORT_AGENT: (id: string) => `/api/export_agent?id=${id}`,
    IMPORT_AGENT_PLAN: '/api/import_agent/plan',
    IMPORT_AGENT: '/api/import_agent',
    TEAMS: '/api/teams',
    TEAM: (id: string) => `/api/teams/${id}`,
    TEAM_MEMBERS: (id: string) => `/api/teams/${id}/members`,
    TEAM_MEMBER: (id: string, memberId: string) =>
      `/api/teams/${id}/members/${encodeURIComponent(memberId)}`,
    TEAM_GRANTS: (id: string) => `/api/teams/${id}/grants`,
    TEAM_TRANSFER_OWNER: (id: string) => `/api/teams/${id}/transfer_owner`,
    RESOURCE_SHARES: (resourceType: string, resourceId: string) =>
      `/api/resource_shares?resource_type=${resourceType}&resource_id=${resourceId}`,
    ALL_TEAMS: '/api/admin/teams',
    PROMPTS: '/api/get_prompts',
    CREATE_PROMPT: '/api/create_prompt',
    DELETE_PROMPT: '/api/delete_prompt',
    UPDATE_PROMPT: '/api/update_prompt',
    SINGLE_PROMPT: (id: string) => `/api/get_single_prompt?id=${id}`,
    DELETE_PATH: (docPath: string) => `/api/delete_old?source_id=${docPath}`,
    MESSAGE_ANALYTICS: '/api/get_message_analytics',
    TOKEN_ANALYTICS: '/api/get_token_analytics',
    FEEDBACK_ANALYTICS: '/api/get_feedback_analytics',
    TOOL_ANALYTICS: '/api/get_tool_analytics',
    SCHEDULE_ANALYTICS: '/api/get_schedule_analytics',
    LOGS: `/api/get_user_logs`,
    MANAGE_SYNC: '/api/manage_sync',
    SYNC_SOURCE: '/api/sync_source',
    REINGEST_SOURCE: '/api/sources/reingest',
    SOURCE_CONFIG: (id: string) => `/api/sources/${id}/config`,
    CREATE_WIKI: '/api/sources/wiki',
    CONVERT_TO_WIKI: (id: string) => `/api/sources/${id}/wiki/convert`,
    ENABLE_GRAPHRAG: (id: string) => `/api/sources/${id}/graphrag/enable`,
    SOURCE_GRAPH: (id: string, limit?: number) =>
      `/api/sources/${id}/graph${limit ? `?limit=${limit}` : ''}`,
    SOURCE_GRAPH_NODE: (id: string, nodeId: string) =>
      `/api/sources/${id}/graph/node/${encodeURIComponent(nodeId)}`,
    TASK_STATUS: (taskId: string) => `/api/task_status?task_id=${taskId}`,
    WIKI_PAGES: (id: string) => `/api/sources/${id}/wiki/pages`,
    WIKI_PAGE: (id: string, path: string) =>
      `/api/sources/${id}/wiki/page?path=${encodeURIComponent(path)}`,
    GET_AVAILABLE_TOOLS: '/api/available_tools',
    GET_USER_TOOLS: '/api/get_tools',
    CREATE_TOOL: '/api/create_tool',
    UPDATE_TOOL_STATUS: '/api/update_tool_status',
    UPDATE_TOOL: '/api/update_tool',
    DELETE_TOOL: '/api/delete_tool',
    PARSE_SPEC: '/api/parse_spec',
    SYNC_CONNECTOR: '/api/connectors/sync',
    CONNECTOR_AUTH: (provider: string) =>
      `/api/connectors/auth?provider=${provider}`,
    CONNECTOR_FILES: '/api/connectors/files',
    CONNECTOR_VALIDATE_SESSION: '/api/connectors/validate-session',
    CONNECTOR_DISCONNECT: '/api/connectors/disconnect',
    GET_CHUNKS: (
      docId: string,
      page: number,
      per_page: number,
      path?: string,
      search?: string,
    ) =>
      `/api/get_chunks?id=${docId}&page=${page}&per_page=${per_page}${
        path ? `&path=${encodeURIComponent(path)}` : ''
      }${search ? `&search=${encodeURIComponent(search)}` : ''}`,
    ADD_CHUNK: '/api/add_chunk',
    DELETE_CHUNK: (docId: string, chunkId: string) =>
      `/api/delete_chunk?id=${docId}&chunk_id=${chunkId}`,
    UPDATE_CHUNK: '/api/update_chunk',
    STORE_ATTACHMENT: '/api/store_attachment',
    STT: '/api/stt',
    TTS: '/api/tts',
    LIVE_STT_START: '/api/stt/live/start',
    LIVE_STT_CHUNK: '/api/stt/live/chunk',
    LIVE_STT_FINISH: '/api/stt/live/finish',
    DIRECTORY_STRUCTURE: (docId: string) =>
      `/api/directory_structure?id=${docId}`,
    MANAGE_SOURCE_FILES: '/api/manage_source_files',
    MCP_TEST_CONNECTION: '/api/mcp_server/test',
    MCP_SAVE_SERVER: '/api/mcp_server/save',
    MCP_AUTH_STATUS: '/api/mcp_server/auth_status',
    AGENT_FOLDERS: '/api/agents/folders/',
    AGENT_FOLDER: (id: string) => `/api/agents/folders/${id}`,
    MOVE_AGENT_TO_FOLDER: '/api/agents/folders/move_agent',
    GET_ARTIFACT: (artifactId: string) => `/api/artifact/${artifactId}`,
    GET_DOCUMENT_ARTIFACT: (artifactId: string) =>
      `/api/artifacts/${artifactId}`,
    LIST_WORKFLOW_RUN_ARTIFACTS: (workflowRunId: string) =>
      `/api/artifacts?workflow_run_id=${encodeURIComponent(workflowRunId)}`,
    DOWNLOAD_ARTIFACT: (
      artifactId: string,
      version?: number,
      disposition?: string,
    ) => {
      const params = new URLSearchParams();
      if (version != null) params.set('version', String(version));
      if (disposition) params.set('disposition', disposition);
      const qs = params.toString();
      return `/api/artifacts/${artifactId}/download${qs ? `?${qs}` : ''}`;
    },
    RESTORE_ARTIFACT: (artifactId: string) =>
      `/api/artifacts/${artifactId}/restore`,
    WORKFLOWS: '/api/workflows',
    WORKFLOW: (id: string) => `/api/workflows/${id}`,
    CUSTOM_MODELS: '/api/user/models',
    CUSTOM_MODEL: (id: string) => `/api/user/models/${id}`,
    CUSTOM_MODEL_TEST: (id: string) => `/api/user/models/${id}/test`,
    CUSTOM_MODEL_TEST_PAYLOAD: '/api/user/models/test',
    AGENT_SCHEDULES: (agentId: string) => `/api/agents/${agentId}/schedules`,
    SCHEDULE: (id: string) => `/api/schedules/${id}`,
    SCHEDULE_RUN_NOW: (id: string) => `/api/schedules/${id}/run`,
    SCHEDULE_RUNS: (id: string, limit?: number, offset?: number) =>
      `/api/schedules/${id}/runs?limit=${limit ?? 50}&offset=${offset ?? 0}`,
    SCHEDULE_RUN: (id: string, runId: string) =>
      `/api/schedules/${id}/runs/${runId}`,
    DEVICES: '/api/devices',
    DEVICE: (id: string) => `/api/devices/${id}`,
    DEVICE_AUTO_APPROVE: (id: string) => `/api/devices/${id}/auto-approve`,
    DEVICE_AUDIT: (id: string) => `/api/devices/${id}/audit`,
    DEVICE_PAIRINGS: '/api/devices/pairings',
    DEVICE_PAIRING: (deviceCode: string) =>
      `/api/devices/pairings/${deviceCode}`,
  },
  V1: {
    CHAT_COMPLETIONS: '/v1/chat/completions',
    MODELS: '/v1/models',
  },
  ADMIN: {
    OVERVIEW: '/api/admin/overview',
    USERS: '/api/admin/users',
    USER: (id: string) => `/api/admin/users/${encodeURIComponent(id)}`,
    USER_ROLE: (id: string) =>
      `/api/admin/users/${encodeURIComponent(id)}/role`,
    USER_REVOKE_SESSIONS: (id: string) =>
      `/api/admin/users/${encodeURIComponent(id)}/revoke-sessions`,
    ADMINS: '/api/admin/admins',
    USAGE: '/api/admin/usage',
    AUDIT: '/api/admin/audit',
    DEVICE_AUDIT: '/api/admin/devices/audit',
  },
  CONVERSATION: {
    ANSWER: '/api/answer',
    ANSWER_STREAMING: '/stream',
    SEARCH: '/api/search',
    FEEDBACK: '/api/feedback',
    CONVERSATION: (id: string) => `/api/get_single_conversation?id=${id}`,
    CONVERSATIONS: '/api/get_conversations',
    SEARCH_CONVERSATIONS: (q: string, limit = 30) =>
      `/api/search_conversations?q=${encodeURIComponent(q)}&limit=${limit}`,
    MESSAGE_TAIL: (messageId: string) => `/api/messages/${messageId}/tail`,
    SHARE_CONVERSATION: (isPromptable: boolean) =>
      `/api/share?isPromptable=${isPromptable}`,
    SHARED_CONVERSATION: (identifier: string) =>
      `/api/shared_conversation/${identifier}`,
    DELETE: (id: string) => `/api/delete_conversation?id=${id}`,
    DELETE_ALL: '/api/delete_all_conversations',
    UPDATE: '/api/update_conversation_name',
  },
};

export default endpoints;
