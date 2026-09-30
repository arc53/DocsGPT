<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>Private AI for agents, assistants and enterprise search</strong>
</p>

<p align="left">
  <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> is an open-source AI platform for building intelligent agents and assistants. Features Agent Builder, deep research tools, document analysis (PDF, Office, web content, and audio), Multi-model support (choose your provider or run locally), and rich API connectivity for agents with actionable tools and integrations. Deploy anywhere with complete privacy control.
</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Stars number](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Forks number](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![link to license file](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://www.bestpractices.dev/projects/9907"><img src="https://www.bestpractices.dev/projects/9907/badge"></a>
  <a href="https://discord.gg/vN7YFfdMpj">![link to discord](https://img.shields.io/discord/1070046503302877216)</a>
  <a href="https://x.com/docsgptai">![X (formerly Twitter) URL](https://img.shields.io/twitter/follow/docsgptai)</a>

<a href="https://docs.docsgpt.cloud/quickstart">⚡️ Quickstart</a> • <a href="https://app.docsgpt.cloud/">☁️ Cloud Version</a> • <a href="https://discord.gg/vN7YFfdMpj">💬 Discord</a>
<br>
<a href="https://docs.docsgpt.cloud/">📖 Documentation</a> • <a href="https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md">👫 Contribute</a> • <a href="https://blog.docsgpt.cloud/">🗞 Blog</a>
<br>

</div>


<div align="center">
  <br>
<img src="https://d3dg1063dc54p9.cloudfront.net/videos/demo-26.gif" alt="video-example-of-docs-gpt" width="800" height="480">
</div>
## 🎃 Hacktoberfest 2026

DocsGPT takes part in [Hacktoberfest](https://hacktoberfest.com/) from October 1 to 31, 2026. We give away T-shirts
for meaningful contributions; the T-shirt design will be revealed later. See [HACKTOBERFEST.md](HACKTOBERFEST.md) for
how to take part.

## Key Features

**Agents and workflows**
- [Agents](https://docs.docsgpt.cloud/Agents/basics) with their own prompt, sources, tools and model, including a research mode for
  multi-step deep research.
- A visual [workflow builder](https://docs.docsgpt.cloud/Agents/nodes) with agent, condition, state and sandboxed code nodes.
- [Schedules](https://docs.docsgpt.cloud/Agents/schedules) that run an agent on a cron expression or once at a set time.
- [Guardrails](https://docs.docsgpt.cloud/Agents/guardrails) that flag, redact or block PII, secrets, prompt injection and ungrounded answers.

**Knowledge**
- Documents: PDF, DOCX, XLSX, PPTX, legacy Office and OpenDocument files, RTF, CSV, EPUB, Markdown, MDX, RST, HTML,
  JSON, TXT, images, and audio (MP3, WAV, M4A, OGG, WebM), which is transcribed. Voice input works in the chat too.
- Remote sources: URLs, sitemaps, a web crawler, GitHub, Reddit, S3 and Linear.
- [Connectors](https://docs.docsgpt.cloud/Sources/Connectors) for Google Drive, SharePoint and Confluence that keep a source in sync.
- [GraphRAG](https://docs.docsgpt.cloud/Sources/GraphRAG) knowledge-graph retrieval and [wiki sources](https://docs.docsgpt.cloud/Sources/Wiki-sources) that an agent
  reads and keeps up to date.
- Grounded answers with source citations.

**Tools**
- Built-in tools (web search, webpage reading, Postgres, notes, memory, notifications and more), an
  [API tool](https://docs.docsgpt.cloud/Tools/api-tool) for any REST API, and an [MCP client](https://docs.docsgpt.cloud/Tools/mcp-tools) for remote MCP servers.
- [Artifacts and code execution](https://docs.docsgpt.cloud/Tools/artifacts-and-code-execution) in a sandbox: documents, slides, spreadsheets
  and files made by code.
- [Remote devices](https://docs.docsgpt.cloud/Tools/remote-device): an agent runs shell commands on a machine paired through `docsgpt-cli`.

**Models**
- [Cloud providers](https://docs.docsgpt.cloud/Models/cloud-providers): OpenAI, Anthropic, Google, Groq, OpenRouter and Novita.
- [Local models](https://docs.docsgpt.cloud/Models/local-inference) through any OpenAI-compatible server, such as Ollama, vLLM, llama.cpp,
  SGLang or TGI, plus [custom models](https://docs.docsgpt.cloud/Models/custom-models) and [fallback models](https://docs.docsgpt.cloud/Models/fallback).
- Vector stores: FAISS, pgvector, Elasticsearch, Qdrant, Milvus and MongoDB.

**APIs and integrations**
- An [Agent API](https://docs.docsgpt.cloud/API/agent-api) with agent keys, an [OpenAI-compatible `/v1` API](https://docs.docsgpt.cloud/API/openai-compatible),
  [webhooks](https://docs.docsgpt.cloud/API/webhooks), [personal access tokens](https://docs.docsgpt.cloud/API/personal-access-tokens), and an
  [MCP server](https://docs.docsgpt.cloud/API/mcp-server) that exposes your agents to MCP clients.
- HTML and React [chat](https://docs.docsgpt.cloud/Extensions/chat-widget) and [search](https://docs.docsgpt.cloud/Extensions/search-widget) widgets, and a
  [Chatwoot](https://docs.docsgpt.cloud/Extensions/Chatwoot-extension) bridge.
- [Community integrations](https://docs.docsgpt.cloud/Extensions/community) in separate repos: [DocsGPT CLI](https://github.com/arc53/DocsGPT-cli)
  and bots for
  [Discord](https://github.com/arc53/discord-docsgpt-extension),
  [Slack](https://github.com/arc53/slack-bot-docsgpt-extenstion) and
  [Telegram](https://github.com/arc53/tg-bot-docsgpt-extenstion).

**Enterprise and operations**
- [OIDC single sign-on and SCIM](https://docs.docsgpt.cloud/Deploying/OIDC-SSO) provisioning, [roles, teams and sharing](https://docs.docsgpt.cloud/Deploying/Access-Control),
  and [usage quotas](https://docs.docsgpt.cloud/Deploying/Usage-Quotas).
- An admin dashboard, analytics and logs, and [OpenTelemetry observability](https://docs.docsgpt.cloud/Deploying/Observability).
- Runs with the installer, [Docker Compose](https://docs.docsgpt.cloud/Deploying/Docker-Deploying), [pip](https://docs.docsgpt.cloud/Deploying/Pip-Install),
  [Kubernetes](https://docs.docsgpt.cloud/Deploying/Kubernetes-Deploying), or [air-gapped](https://docs.docsgpt.cloud/Deploying/Air-Gapped).

## Roadmap

What we are working on next lives on the [DocsGPT roadmap](https://github.com/orgs/arc53/projects/2), and what each
release shipped is in the [changelog](https://docs.docsgpt.cloud/changelog). Please don't hesitate to contribute or create issues, it helps
us improve DocsGPT!

### Production Support / Help for Companies:

We're eager to provide personalized assistance when deploying your DocsGPT to a live environment.

[Get a Demo :wave:](https://www.docsgpt.cloud/contact)⁠

[Send Email :email:](mailto:support@docsgpt.cloud?subject=DocsGPT%20support%2Fsolutions)

## QuickStart

> [!Note]
> DocsGPT runs on [Docker](https://docs.docker.com/engine/install/). The installer checks for it first.

**macOS and Linux:**

```bash
curl -fsSL https://docs.ac/install | bash
```

**Windows (PowerShell):**

```powershell
irm https://docs.ac/install.ps1 | iex
```

The installer gets [uv](https://docs.astral.sh/uv/), installs the `docsgpt` Python package with it, and runs `docsgpt up`. That asks who should reach DocsGPT (only this computer, your network, or a domain with HTTPS) and which model provider to use, then starts it, at http://localhost:7091 for a local install. Afterwards, `docsgpt status`, `docsgpt logs`, `docsgpt upgrade`, `docsgpt down` and `docsgpt uninstall` manage it.

To read the script before running it:

```bash
curl -fsSL https://docs.ac/install -o install.sh
less install.sh
bash install.sh
```

A more detailed [Quickstart](https://docs.docsgpt.cloud/quickstart) is available in our documentation.

### From a clone, with the setup script

1. **Clone the repository:**

   ```bash
   git clone https://github.com/arc53/DocsGPT.git
   cd DocsGPT
   ```

**For macOS and Linux:**

2. **Run the setup script:**

   ```bash
   ./setup.sh
   ```

**For Windows:**

2. **Run the PowerShell setup script:**

   ```powershell
   PowerShell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

Either script will guide you through setting up DocsGPT. Five options are available: using the public API, running locally, connecting to a local inference engine, using a cloud API provider, or building the docker image locally. The scripts will automatically configure your `.env` file and handle necessary downloads and installations based on your chosen option.

**Navigate to http://localhost:5173/**

To stop DocsGPT, open a terminal in the `DocsGPT` directory and run the `docker compose ... down` command the setup script printed at the end, for example:

```bash
docker compose --env-file .env -f deployment/docker-compose-hub.yaml down
```

If you chose the Ollama option, the printed command also names the Ollama overlay file; use it, or the Ollama container keeps running.

The setup scripts run the `develop` images, built from the `main` branch. To run a release instead, set `DOCSGPT_IMAGE_TAG=<version>` in `.env`.

> [!Warning]
> The setup scripts and the checkout Compose files are meant for local use: DocsGPT, Postgres and Redis are reachable from this computer only. If you tell the script to expose DocsGPT on your network, set up authentication when it asks. Without it every visitor shares one account, with its documents and connected services. For a server, use the installer above and read the [security checklist](https://docs.docsgpt.cloud/Deploying/Security).

> [!Note]
> For development environment setup instructions, please refer to the [Development Environment Guide](https://docs.docsgpt.cloud/Deploying/Development-Environment).

## Contributing

Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file for information about how to get involved. We welcome issues, questions, and pull requests.

## Architecture

DocsGPT runs as an API, a Celery worker, Postgres for user data, Redis, and a vector store. The
[architecture guide](https://docs.docsgpt.cloud/Concepts/Architecture) shows how they fit together, how an answer and a document upload flow through them,
and how each deployment option lays them out.

## Project Structure

- `docsgpt/`: the backend (the `docsgpt` Python package): the Flask API and its ASGI entrypoint, agents, tools,
  retrieval, parsers, the Celery worker, and the `docsgpt` command.
- `application/`: a deprecated import alias for `docsgpt`, kept for one release.
- `frontend/`: the web UI, built with [Vite](https://vitejs.dev/) and [React](https://react.dev/).
- `extensions/`: the Chatwoot bridge and the React widget (published to npm as `docsgpt`).
- `deployment/`: Docker Compose files, Kubernetes manifests, the installer scripts and the sandbox image.
- `docs/`: the documentation site at [docs.docsgpt.cloud](https://docs.docsgpt.cloud).
- `tests/`: backend unit and integration tests, and the end-to-end suite.
- `scripts/`: maintenance and migration scripts.

## Code Of Conduct

We as members, contributors, and leaders, pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, religion, or sexual identity and orientation. Please refer to the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) file for more information about contributing.

## Many Thanks To Our Contributors⚡

<a href="https://github.com/arc53/DocsGPT/graphs/contributors" alt="View Contributors">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" alt="Contributors" />
</a>

## License

The source code license is [MIT](https://opensource.org/license/mit/), as described in the [LICENSE](LICENSE) file.

## This project is supported by:

<p>
  <a href="https://www.digitalocean.com/?utm_medium=opensource&utm_source=DocsGPT">
    <img src="https://opensource.nyc3.cdn.digitaloceanspaces.com/attribution/assets/SVG/DO_Logo_horizontal_blue.svg" width="201px">
  </a>
</p>
<p>
  <a href="https://get.neon.com/docsgpt">
    <img width="201" alt="color" src="https://github.com/user-attachments/assets/7d9813b7-0e6d-403f-b5af-68af066b326f" />
  </a>
  
</p>
