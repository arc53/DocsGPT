<h1 align="center">
  <img src="https://github.com/arc53/DocsGPT/blob/main/Readme%20Logo.png" alt="DocsGPT Banner"> 
</h1>


<p align="center">
  <strong>Open-Source Documentation Assistant</strong>
</p>


<p align="center">
  <img src="https://img.shields.io/github/stars/arc53/docsgpt?style=social" alt="GitHub Stars">
  <img src="https://img.shields.io/github/forks/arc53/docsgpt?style=social" alt="GitHub Forks">
  <img src="https://img.shields.io/github/license/arc53/docsgpt" alt="License">
  <img src="https://img.shields.io/discord/1070046503302877216" alt="Discord Chat">
</p>


## Table of Contents

- [About DocsGPT](#about-docsgpt)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Contribution Guidelines](#contribution-guidelines)
- [Community and Support](#community-and-support)
- [Roadmap](#roadmap)
- [Acknowledgments](#acknowledgments)

## About DocsGPT
<p align="left">
  <strong>DocsGPT</strong> is a cutting-edge open-source solution that streamlines the process of finding information in project documentation. With its integration of the powerful <strong>GPT</strong> models, developers can easily ask questions about a project and receive accurate answers.

Say goodbye to time-consuming manual searches, and let <strong>DocsGPT</strong> help you quickly find the information you need. Try it out and see how it revolutionizes your project documentation experience. Contribute to its development and be a part of the future of AI-powered assistance.

<hr>


### [🎉 Join the Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

![video-example-of-docs-gpt](https://d3dg1063dc54p9.cloudfront.net/videos/demov3.gif)


## Features

![Group 9](https://user-images.githubusercontent.com/17906039/220427472-2644cff4-7666-46a5-819f-fc4a521f63c7.png)

<hr>


## Installation

To install DocsGPT, follow the [installation instructions](docs/installation.md) based on your platform and environment.


## Usage

Learn how to use DocsGPT in our [usage guide](https://docs.docsgpt.co.uk/).


## API Documentation

For developers, explore the [API documentation](docs/api.md) to integrate DocsGPT into your applications.


## Contribution Guidelines

We welcome contributions! Read our [contribution guidelines](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md) to get started.


## Community and Support

- Join our community on [Discord](https://discord.gg/n5BX8dh8rU).

- Get personalized support for deploying DocsGPT in a live environment: [Support](https://airtable.com/appdeaL0F1qV8Bl2C/shrrJF1Ll7btCJRbP).

- Email us at [contact@arc53.com](mailto:contact@arc53.com) for assistance or inquiries.


## Roadmap

Check our [roadmap](https://github.com/orgs/arc53/projects/2) for upcoming features and milestones. Contribute or create issues to help us improve DocsGPT!


## Our Open-Source models optimized for DocsGPT:

| Name                                                         | Base Model  | Requirements (or similar) |
| ------------------------------------------------------------ | ----------- | ------------------------- |
| [Docsgpt-7b-falcon](https://huggingface.co/Arc53/docsgpt-7b-falcon) | Falcon-7b   | 1xA10G gpu                |
| [Docsgpt-14b](https://huggingface.co/Arc53/docsgpt-14b)      | llama-2-14b | 2xA10 gpu's               |
| [Docsgpt-40b-falcon](https://huggingface.co/Arc53/docsgpt-40b-falcon) | falcon-40b  | 8xA10G gpu's              |


If you don't have enough resources to run it, you can use bitsnbytes to quantize.


## Useful links

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

   ```bash
   API_KEY=Yourkey
   VITE_API_STREAMING=true
   ```

You can create this file manually using a text editor or use a command-line text editor like `echo` in Windows Command Prompt:

   ```bash
   echo API_KEY=Yourkey > .env 
   echo VITE_API_STREAMING=true >> .env
   ```

See optional environment variables in the `/.env-template`  and`/application/.env_sample` files.

3. Run the following command to set up the project and start the application: 

   ```bash
   ./run-with-docker-compose.sh
   ```

4.  Open your web browser and navigate to [http://localhost:5173/](http://localhost:5173/). 

To stop the application, press `Ctrl + C` in your terminal or Command Prompt. 


## Development environments


### Spin up mongo and redis

For development, only two containers are used from `docker-compose.yaml` (by deleting all services except for Redis and Mongo). 
See file [docker-compose-dev.yaml](./docker-compose-dev.yaml).

Run the following commands:

```bash
docker compose -f docker-compose-dev.yaml build
docker compose -f docker-compose-dev.yaml up -d
```

### Run the Backend

Make sure you have Python 3.10 or 3.11 installed.

1. Export required environment variables or prepare a `.env` file in the `/application` folder. You can create a `.env` file using Windows Command Prompt like this:

   ```bash
   echo API_KEY=Yourkey > .env
   echo EMBEDDINGS_KEY=YourEmbeddingsKey >> .env
   ```

Replace `Yourkey` and `YourEmbeddingsKey` with your actual API keys.

(check out [`application/core/settings.py`](application/core/settings.py) if you want to see more config options.)

2. (optional) Create a Python virtual environment:

```commandline
python -m venv venv
. venv/bin/activate    # On linux
venv\Scripts\activate  # On Windows
```

3. Change to the `application/` subdir and install dependencies for the backend:

```commandline
pip install -r application/requirements.txt
```

4. Run the app using the following command:

   ```bash
   flask run --host=0.0.0.0 --port=7091
   ```

5. Start the worker with the following command:

   ```bash
   celery -A application.app.celery worker -l INFO
   ```


### Start frontend 

Make sure you have Node version 16 or higher.

1. Navigate to the `/frontend` folder.

2. Install dependencies by running:

   ```bash
   npm install
   ```

   

3. Run the app using:

   ```bash
   npm run dev
   ```

   

## Acknowledgments

<a href="[https://github.com/arc53/DocsGPT/graphs/contributors](https://docsgpt.arc53.com/)">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" />
</a>

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)

---

[Live Preview](https://docsgpt.arc53.com/) | [Documentation](https://docs.docsgpt.co.uk/) | [GitHub Repository](https://github.com/arc53/DocsGPT)
