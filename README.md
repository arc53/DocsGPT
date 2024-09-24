<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>Open-Source Documentation Assistant</strong>
</p>

<p align="left">
  <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> is a cutting-edge open-source solution that streamlines the process of finding information in the project documentation. With its integration of the powerful <strong>GPT</strong> models, developers can easily ask questions about a project and receive accurate answers.
  
Say goodbye to time-consuming manual searches, and let <strong><a href="https://www.docsgpt.cloud/">DocsGPT</a></strong> help you quickly find the information you need. Try it out and see how it revolutionizes your project documentation experience. Contribute to its development and be a part of the future of AI-powered assistance.
</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Stars number](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![link to main GitHub showing Forks number](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![link to license file](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![link to discord](https://img.shields.io/discord/1070046503302877216)</a>
  <a href="https://twitter.com/docsgptai">![X (formerly Twitter) URL](https://img.shields.io/twitter/follow/docsgptai)</a>

 
</div>

### 🎃 [Hacktoberfest Prizes, Rules & Q&A](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md) 🎃

### Production Support / Help for Companies:

We're eager to provide personalized assistance when deploying your DocsGPT to a live environment.

- [Get Enterprise / teams Demo :wave:](https://www.docsgpt.cloud/contact)
- [Send Email :email:](mailto:contact@arc53.com?subject=DocsGPT%20support%2Fsolutions)

![video-example-of-docs-gpt](https://d3dg1063dc54p9.cloudfront.net/videos/demov3.gif)

## Roadmap

You can find our roadmap [here](https://github.com/orgs/arc53/projects/2). Please don't hesitate to contribute or create issues, it helps us improve DocsGPT!

## Our Open-Source Models Optimized for DocsGPT:

| Name                                                                  | Base Model  | Requirements (or similar) |
| --------------------------------------------------------------------- | ----------- | ------------------------- |
| [Docsgpt-7b-mistral](https://huggingface.co/Arc53/docsgpt-7b-mistral)   | Mistral-7b   | 1xA10G gpu                |
| [Docsgpt-14b](https://huggingface.co/Arc53/docsgpt-14b)               | llama-2-14b | 2xA10 gpu's               |
| [Docsgpt-40b-falcon](https://huggingface.co/Arc53/docsgpt-40b-falcon) | falcon-40b  | 8xA10G gpu's              |

If you don't have enough resources to run it, you can use bitsnbytes to quantize.

## End to End AI Framework for Information Retrieval

![Architecture chart](https://github.com/user-attachments/assets/fc6a7841-ddfc-45e6-b5a0-d05fe648cbe2)

## Useful Links

- :mag: :fire: [Cloud Version](https://app.docsgpt.cloud/)

- :speech_balloon: :tada: [Join our Discord](https://discord.gg/n5BX8dh8rU)

- :books: :sunglasses: [Guides](https://docs.docsgpt.cloud/)

- :couple: [Interested in contributing?](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md)

- :file_folder: :rocket: [How to use any other documentation](https://docs.docsgpt.cloud/Guides/How-to-train-on-other-documentation)

- :house: :closed_lock_with_key: [How to host it locally (so all data will stay on-premises)](https://docs.docsgpt.cloud/Guides/How-to-use-different-LLM)

## Project Structure

- Application - Flask app (main application).

- Extensions - Chrome extension.

- Scripts - Script that creates similarity search index for other libraries.

- Frontend - Frontend uses <a href="https://vitejs.dev/">Vite</a> and <a href="https://react.dev/">React</a>.

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
> Make sure you have Python 3.10 or 3.11 installed.

1. Export required environment variables or prepare a `.env` file in the project folder:
   - Copy [.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) and create `.env`.

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

## Code Of Conduct

We as members, contributors, and leaders, pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, religion, or sexual identity and orientation. Please refer to the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) file for more information about contributing.

## Many Thanks To Our Contributors⚡

<a href="https://github.com/arc53/DocsGPT/graphs/contributors" alt="View Contributors">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" alt="Contributors" />
</a>

## License

The source code license is [MIT](https://opensource.org/license/mit/), as described in the [LICENSE](LICENSE) file.

Built with [:bird: :link: LangChain](https://github.com/hwchase17/langchain)
