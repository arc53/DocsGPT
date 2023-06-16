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
  
  <a href="https://discord.gg/n5BX8dh8rU">![example1](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![example2](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![example3](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![example3](https://img.shields.io/discord/1070046503302877216)</a>
  
</div>

![video-example-of-docs-gpt](https://d3dg1063dc54p9.cloudfront.net/videos/demov3.gif)


## Our Livestream coming up on 17th of June at 6pm UK time
[DocsGPT Live: Gen AI in business and Fine tuning models](https://discord.gg/pbCTxb8z?event=1117425466681335808)


## Features

![Group 9](https://user-images.githubusercontent.com/17906039/220427472-2644cff4-7666-46a5-819f-fc4a521f63c7.png)



## Roadmap

You can find our [Roadmap](https://github.com/orgs/arc53/projects/2) here, please don't hesitate contributing or creating issues, it helps us make DocsGPT better!

## [DocsGPT-7B](https://huggingface.co/Arc53/DocsGPT-7B) Our finetuned model to help you keep your data private, fine-tuned on top on MPT-7b

## [Live preview](https://docsgpt.arc53.com/)

## [Join Our Discord](https://discord.gg/n5BX8dh8rU)


## Project structure
- Application - flask app (main application)

- Extensions - chrome extension

- Scripts - script that creates similarity search index and store for other libraries. 

- frontend - frontend in vite and

## QuickStart

Note: Make sure you have docker installed

1. Open dowload this repository with `git clone https://github.com/arc53/DocsGPT.git`
2. Create .env file in your root directory and set your OPENAI_API_KEY with your openai api key and  VITE_API_STREAMING to true or false if you dont want streaming answers
   Should look like this inside
   
   ```
   OPENAI_API_KEY=Yourkey
   VITE_API_STREAMING=true
   ```
3. Run `docker-compose build && docker-compose up`
4. Navigate to http://localhost:5173/

To stop just run Ctrl + C

## Development environments

### Spin up mongo and redis
For development only 2 containers are used from docker-compose.yaml (by deleting all services except for redis and mongo). 
See file [docker-compose-dev.yaml](./docker-compose-dev.yaml).

Run
```
docker compose -f docker-compose-dev.yaml build
docker compose -f docker-compose-dev.yaml up -d
```

### Run the backend

Make sure you have Python 3.10 or 3.11 installed.

1. Export required environment variables
```commandline
export CELERY_BROKER_URL=redis://localhost:6379/0   
export CELERY_RESULT_BACKEND=redis://localhost:6379/1
export MONGO_URI=mongodb://localhost:27017/docsgpt
```
2. Prepare .env file
Copy `.env_sample` and create `.env` with your OpenAI API token
3. (optional) Create a python virtual environment
```commandline
python -m venv venv
. venv/bin/activate
```
4. Change to `application/` subdir and install dependencies for the backend
```commandline
cd application/ 
pip install -r requirements.txt
```
5. Run the app `python wsgi.py`
6. Start worker with `celery -A app.celery worker -l INFO`

### Start frontend 
Make sure you have Node version 16+

1. Navigate to `/frontend` folder
2. Install dependencies
`npm install`
3. Run the app 
`npm run dev`


[How to install the Chrome extension](https://github.com/arc53/docsgpt/wiki#launch-chrome-extension)


## [Guides](https://github.com/arc53/docsgpt/wiki)

## [Interested in contributing?](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md)

## [How to use any other documentation](https://github.com/arc53/docsgpt/wiki/How-to-train-on-other-documentation)

## [How to host it locally (so all data will stay on-premises)](https://github.com/arc53/DocsGPT/wiki/How-to-use-different-LLM's#hosting-everything-locally)

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)

