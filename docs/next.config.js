const nextra = require('nextra').default;

const withNextra = nextra({
  defaultShowCopyCode: true,
});

// Old URL -> current URL for every page that moved or was retired. Each
// target is a live page, so no redirect points at another redirect.
const movedPages = [
  // Retired hosting guides: the installer's --domain flow covers any VM.
  ['/Deploying/Hosting-the-app', '/Deploying'],
  ['/Deploying/Amazon-Lightsail', '/Deploying'],
  ['/Deploying/Railway', '/Deploying'],

  // Guides/ was split up by topic.
  ['/Guides/Architecture', '/Concepts/Architecture'],
  ['/Guides/Customising-prompts', '/Agents/prompts'],
  ['/Guides/My-AI-answers-questions-using-external-knowledge', '/Agents/prompts'],
  ['/Guides/compression', '/Agents/context-compression'],
  ['/Guides/Benchmarking-Agents', '/Agents/benchmarking'],
  ['/Guides/How-to-train-on-other-documentation', '/Sources/adding-knowledge'],
  ['/Guides/How-to-use-different-LLM', '/Models/fallback'],
  ['/Guides/ocr', '/Sources/ocr'],
  ['/Guides/Connectors', '/Sources/Connectors'],
  ['/Guides/Integrations/google-drive-connector', '/Sources/Connectors/google-drive'],
  ['/Guides/Integrations/sharepoint-connector', '/Sources/Connectors/sharepoint'],
  ['/Guides/Integrations/confluence-connector', '/Sources/Connectors/confluence'],
  ['/Guides/Integrations/github-connector', '/Sources/Connectors/github'],
  ['/Guides/Integrations/linear-connector', '/Sources/Connectors/linear'],
  ['/Guides/Integrations/s3-connector', '/Sources/Connectors/s3'],
  ['/Guides/Integrations/mcp-tool-integration', '/Tools/mcp-tools'],

  // API pages gathered under API/.
  ['/Agents/api', '/API/agent-api'],
  ['/Agents/openai-compatible', '/API/openai-compatible'],
  ['/Agents/webhooks', '/API/webhooks'],
  ['/Agents/notifications', '/API/realtime-events'],
  ['/Extensions/api-key-guide', '/API/agent-keys'],
  ['/Extensions/personal-access-tokens', '/API/personal-access-tokens'],

  // The Chrome extension left the repo; community integrations are listed here.
  ['/Extensions/Chrome-extension', '/Extensions/community'],
];

module.exports = withNextra({
  reactStrictMode: true,
  async redirects() {
    return movedPages.map(([source, destination]) => ({
      source,
      destination,
      permanent: true,
    }));
  },
});
