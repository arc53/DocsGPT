const endpoints = {
  USER: {
    API_KEYS: '/api/get_api_keys',
    CREATE_API_KEY: '/api/create_api_key',
    DELETE_API_KEY: '/api/delete_api_key',
    PROMPTS: '/api/get_prompts',
    CREATE_PROMPT: '/api/create_prompt',
    DELETE_PROMPT: '/api/delete_prompt',
    UPDATE_PROMPT: '/api/update_prompt',
    SINGLE_PROMPT: (id: string) => `/api/get_single_prompt?id=${id}`,
    DELETE_PATH: (docPath: string) => `/api/delete_old?path=${docPath}`,
  },
  CONVERSATION: {
    ANSWER: '/api/answer',
    ANSWER_STREAMING: '/stream',
    SEARCH: '/api/search',
    FEEDBACK: '/api/feedback',
    SHARED_CONVERSATION: (identifier: string) =>
      `/api/shared_conversation/${identifier}`,
  },
};

export default endpoints;
