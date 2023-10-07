<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>Open-Source Documentation Assistant</strong>
</p>

<p align="left">
  <strong>DocsGPT</strong> is a cutting-edge open-source solution that streamlines the process of finding information in project documentation. With its integration of the powerful <strong>GPT</strong> models, developers can easily ask questions about a project and receive accurate answers.
  
Say goodbye to time-consuming manual searches, and let <strong>DocsGPT</strong> help you quickly find the information you need. Try it out and see how it revolutionizes your project documentation experience. Contribute to its development and be a part of the future of AI-powered assistance.
</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT">![example1](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![example2](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![example3](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![example3](https://img.shields.io/discord/1070046503302877216)</a>
 
</div>

### Production Support / Help for companies: 

We're eager to provide personalized assistance when deploying your DocsGPT to a live environment.
- [Schedule Demo 👋](https://cal.com/arc53/docsgpt-demo-b2b?date=2023-10-04&month=2023-10)
- [Send Email ✉️](mailto:contact@arc53.com?subject=DocsGPT%20support%2Fsolutions)
  
### [🎉 Join the Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

![video-example-of-docs-gpt](https://d3dg1063dc54p9.cloudfront.net/videos/demov3.gif)


## Roadmap

You can find our roadmap [here](https://github.com/orgs/arc53/projects/2). Please don't hesitate to contribute or create issues, it helps us improve DocsGPT!

## Our Open-Source models optimized for DocsGPT:

| Name              | Base Model | Requirements (or similar)                        |
|-------------------|------------|----------------------------------------------------------|
| [Docsgpt-7b-falcon](https://huggingface.co/Arc53/docsgpt-7b-falcon)  | Falcon-7b  |  1xA10G gpu   |
| [Docsgpt-14b](https://huggingface.co/Arc53/docsgpt-14b)              | llama-2-14b    | 2xA10 gpu's   |
| [Docsgpt-40b-falcon](https://huggingface.co/Arc53/docsgpt-40b-falcon)       | falcon-40b     | 8xA10G gpu's  |


If you don't have enough resources to run it, you can use bitsnbytes to quantize.


## Features

![Group 9](https://user-images.githubusercontent.com/17906039/220427472-2644cff4-7666-46a5-819f-fc4a521f63c7.png)


## Useful links
 [Live preview](https://docsgpt.arc53.com/)
 
 [Join our Discord](https://discord.gg/n5BX8dh8rU)
 
 [Guides](https://docs.docsgpt.co.uk/)

 [Interested in contributing?](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md)

 [How to use any other documentation](https://docs.docsgpt.co.uk/Guides/How-to-train-on-other-documentation)

 [How to host it locally (so all data will stay on-premises)](https://docs.docsgpt.co.uk/Guides/How-to-use-different-LLM)


## Project structure
- Application - Flask app (main application).

- Extensions - Chrome extension.

- Scripts - Script that creates similarity search index and stores for other libraries. 

- Frontend - Frontend uses Vite and React.

## QuickStart

Note: Make sure you have Docker installed

On Mac OS or Linux, write:

`./setup.sh`

It will install all the dependencies and allow you to download the local model or use OpenAI.

Otherwise, refer to this Guide:

1. Download and open this repository with `git clone https://github.com/arc53/DocsGPT.git`
2. Create a `.env` file in your root directory and set the env variable `OPENAI_API_KEY` with your OpenAI API key and  `VITE_API_STREAMING` to true or false, depending on if you want streaming answers or not.
   It should look like this inside:
   
   ```
   API_KEY=Yourkey
   VITE_API_STREAMING=true
   ```
   See optional environment variables in the `/.env-template` and `/application/.env_sample` files.
3. Run `./run-with-docker-compose.sh`.
4. Navigate to http://localhost:5173/.

To stop, just run `Ctrl + C`.

## Development environments

### Spin up mongo and redis
For development, only two containers are used from `docker-compose.yaml` (by deleting all services except for Redis and Mongo). 
See file [docker-compose-dev.yaml](./docker-compose-dev.yaml).

Run
```
docker compose -f docker-compose-dev.yaml build
docker compose -f docker-compose-dev.yaml up -d
```

### Run the backend

Make sure you have Python 3.10 or 3.11 installed.

1. Export required environment variables or prepare a `.env` file in the `/application` folder:
   - Copy `.env_sample` and create `.env` with your OpenAI API token for the `API_KEY` and `EMBEDDINGS_KEY` fields.

(check out [`application/core/settings.py`](application/core/settings.py) if you want to see more config options.)

2. (optional) Create a Python virtual environment:
 On Mac OS or Linux 
```commandline
python -m venv venv
. venv/bin/activate
```
On Windows
```commandline
python -m venv venv
venv/Scripts/activate
```
3. Change to the `application/` subdir and install dependencies for the backend:
```commandline
pip install -r application/requirements.txt
```
4. Run the app using `flask run --host=0.0.0.0 --port=7091`.
5. Start worker with `celery -A application.app.celery worker -l INFO`.

### Start frontend 

Make sure you have Node version 16 or higher.

1. Navigate to the `/frontend` folder.
2. Install dependencies by running `npm install`.
3. Run the app using `npm run dev`.

## Many Thanks To Our Contributors

<a href="[https://github.com/arc53/DocsGPT/graphs/contributors](https://docsgpt.arc53.com/)">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" />
</a>


Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)
