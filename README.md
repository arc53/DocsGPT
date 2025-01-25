<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>Open-Source RAG Assistant</strong>
</p>

<p align="left">
  <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> is an open-source genAI tool that helps users get reliable answers from any knowledge source, while avoiding hallucinations. It enables quick and reliable information retrieval, with tooling and agentic system capability built in.
</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Stars number](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Forks number](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![link to license file](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![link to discord](https://img.shields.io/discord/1070046503302877216)</a>
  <a href="https://twitter.com/docsgptai">![X (formerly Twitter) URL](https://img.shields.io/twitter/follow/docsgptai)</a>

  <br>

  [☁️ Cloud Version](https://app.docsgpt.cloud/) • [💬 Discord](https://discord.gg/n5BX8dh8rU) • [📖 Guides](https://docs.docsgpt.cloud/)
  <br>
  [👫 Contribute](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md) • [🏠 Self-host](https://docs.docsgpt.cloud/Guides/How-to-use-different-LLM) • [⚡️ Quickstart](https://github.com/arc53/DocsGPT#quickstart) 

</div>
<div align="center">
<img src="https://d3dg1063dc54p9.cloudfront.net/videos/demov4.gif" alt="video-example-of-docs-gpt" width="800" height="450">
</div>
<h3 align="left">
  <strong>Key Features:</strong>
</h3>
<ul align="left">
    <li><strong>🗂️ Wide Format Support:</strong> Reads PDF, DOCX, CSV, XLSX, EPUB, MD, RST, HTML, MDX, JSON, PPTX, and images.</li>
    <li><strong>🌐 Web & Data Integration:</strong> Ingests from URLs, sitemaps, Reddit, GitHub and web crawlers.</li>
    <li><strong>✅ Reliable Answers:</strong> Get accurate, hallucination-free responses with source citations viewable in a clean UI.</li>
    <li><strong>🔗 Actionable Tooling:</strong> Connect to APIs, tools, and other services to enable LLM actions.</li>
    <li><strong>🧩 Pre-built Integrations:</strong> Use readily available HTML/React chat widgets, search tools, Discord/Telegram bots, and more.</li>
    <li><strong>🔌 Flexible Deployment:</strong> Works with major LLMs (OpenAI, Google, Anthropic) and local models (Ollama, llama_cpp).</li>
    <li><strong>🏢 Secure & Scalable:</strong> Run privately and securely with Kubernetes support, designed for enterprise-grade reliability.</li>
</ul>

## Roadmap

- [x] Full GoogleAI compatibility (Jan 2025)
- [x] Add tools (Jan 2025)
- [ ] Anthropic Tool compatibility
- [ ] Add triggerable actions / tools
- [ ] Add oath2 authentication for tools and sources
- [ ] Manually updating chunks in the app UI
- [ ] Devcontainer for easy development
- [ ] Chatbots menu re-design to handle tools, scheduling, and more

You can find our full roadmap [here](https://github.com/orgs/arc53/projects/2). Please don't hesitate to contribute or create issues, it helps us improve DocsGPT!

### Production Support / Help for Companies:

We're eager to provide personalized assistance when deploying your DocsGPT to a live environment.

[Get a Demo :wave:](https://www.docsgpt.cloud/contact)⁠

[Send Email :email:](mailto:support@docsgpt.cloud?subject=DocsGPT%20support%2Fsolutions)


## QuickStart

> [!Note]
> Make sure you have [Docker](https://docs.docker.com/engine/install/) installed

On Mac OS or Linux, write:

`./setup.sh`

It will install all the dependencies and allow you to download the local model, use OpenAI or use our LLM API.

Otherwise, refer to this Guide for Windows:

1. Download and open this repository with `git clone https://github.com/arc53/DocsGPT.git`
2. Create a `.env` file in your root directory and set the env variables and `VITE_API_STREAMING` to true or false, depending on whether you want streaming answers or not.
   It should look like this inside:

   ```
   LLM_NAME=[docsgpt or openai or others] 
   VITE_API_STREAMING=true
   API_KEY=[if LLM_NAME is openai]
   ```

   See optional environment variables in the [/.env-template](https://github.com/arc53/DocsGPT/blob/main/.env-template) and [/application/.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) files.

3. Run [./run-with-docker-compose.sh](https://github.com/arc53/DocsGPT/blob/main/run-with-docker-compose.sh).
4. Navigate to http://localhost:5173/.

To stop, just run `Ctrl + C`.

## Development Environments

### Spin up Mongo and Redis

For development, only two containers are used from [docker-compose.yaml](https://github.com/arc53/DocsGPT/blob/main/docker-compose.yaml) (by deleting all services except for Redis and Mongo).
See file [docker-compose-dev.yaml](./docker-compose-dev.yaml).

Run

```
docker compose -f docker-compose-dev.yaml build
docker compose -f docker-compose-dev.yaml up -d
```

### Run the Backend

> [!Note]
> Make sure you have Python 3.12 installed.

1. Export required environment variables or prepare a `.env` file in the project folder:
   - Copy [.env-template](https://github.com/arc53/DocsGPT/blob/main/application/.env-template) and create `.env`.

(check out [`application/core/settings.py`](application/core/settings.py) if you want to see more config options.)

2. (optional) Create a Python virtual environment:
   You can follow the [Python official documentation](https://docs.python.org/3/tutorial/venv.html) for virtual environments.

a) On Mac OS and Linux

```commandline
python -m venv venv
. venv/bin/activate
```

b) On Windows

```commandline
python -m venv venv
 venv/Scripts/activate
```

3. Download embedding model and save it in the `model/` folder:
You can use the script below, or download it manually from [here](https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip), unzip it and save it in the `model/` folder.

```commandline
wget https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip
unzip mpnet-base-v2.zip -d model
rm mpnet-base-v2.zip
```

4. Install dependencies for the backend:

```commandline
pip install -r application/requirements.txt
```

5. Run the app using `flask --app application/app.py run --host=0.0.0.0 --port=7091`.
6. Start worker with `celery -A application.app.celery worker -l INFO`.

### Start Frontend

> [!Note]
> Make sure you have Node version 16 or higher.

1. Navigate to the [/frontend](https://github.com/arc53/DocsGPT/tree/main/frontend) folder.
2. Install the required packages `husky` and `vite` (ignore if already installed).

```commandline
npm install husky -g
npm install vite -g
```

3. Install dependencies by running `npm install --include=dev`.
4. Run the app using `npm run dev`.


## Contributing

Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file for information about how to get involved. We welcome issues, questions, and pull requests.

## Architecture

![Architecture chart](https://github.com/user-attachments/assets/fc6a7841-ddfc-45e6-b5a0-d05fe648cbe2)

## Project Structure

- Application - Flask app (main application).

- Extensions - Extensions, like react widget or discord bot.

- Frontend - Frontend uses <a href="https://vitejs.dev/">Vite</a> and <a href="https://react.dev/">React</a>.

- Scripts - Miscellaneous scripts.

## Code Of Conduct

We as members, contributors, and leaders, pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, religion, or sexual identity and orientation. Please refer to the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) file for more information about contributing.


## Many Thanks To Our Contributors⚡

<a href="https://github.com/arc53/DocsGPT/graphs/contributors" alt="View Contributors">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" alt="Contributors" />
</a>

## License

The source code license is [MIT](https://opensource.org/license/mit/), as described in the [LICENSE](LICENSE) file.

<p>This project is supported by:</p>
<p>
  <a href="https://www.digitalocean.com/?utm_medium=opensource&utm_source=DocsGPT">
    <img src="https://opensource.nyc3.cdn.digitaloceanspaces.com/attribution/assets/SVG/DO_Logo_horizontal_blue.svg" width="201px">
  </a>
</p>
