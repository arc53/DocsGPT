<h1 align="center">
  DocsGPT  🦖
</h1>

<p align="center">
  <strong>Open-Source Documentation Assistant</strong>
</p>

<p align="left">
  Introducing <strong><a href="https://docsgpt.arc53.com/">DocsGPT</a></strong>: an advanced open-source tool designed to simplify the task of searching for information within project documentation. By harnessing the utilities of the powerful <strong>GPT</strong> models, developers can effortlessly inquire about project details and receive precise responses.
  
Bid goodbye to the arduous process of manual searches, and let <strong><a href="https://docsgpt.arc53.com/">DocsGPT</a></strong> swiftly uncover the information you seek. Give it a try and witness the transformation it brings to your project documentation experience. 

Join us in contributing to its development and become a valued part of the promising future of AI-powered assistance, shaping the way it revolutionizes documentation for everyone.

</p>

<div align="center">
  
  <a href="https://github.com/arc53/DocsGPT">![example1](https://img.shields.io/github/stars/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT">![example2](https://img.shields.io/github/forks/arc53/docsgpt?style=social)</a>
  <a href="https://github.com/arc53/DocsGPT/blob/main/LICENSE">![example3](https://img.shields.io/github/license/arc53/docsgpt)</a>
  <a href="https://discord.gg/n5BX8dh8rU">![example3](https://img.shields.io/discord/1070046503302877216)</a>
 
</div>

### Production Support / Help for companies: 

We're excited to offer personalized assistance for the deployment of DocsGPT in your live environment.
- [Book A Demo 👋](https://airtable.com/appdeaL0F1qV8Bl2C/shrrJF1Ll7btCJRbP)
- [Send An Email ✉️](mailto:contact@arc53.com?subject=DocsGPT%20support%2Fsolutions)
  
### [🎉 Participate in Hacktoberfest with DocsGPT and Earn a Free T-shirt! 🎉](https://github.com/arc53/DocsGPT/blob/main/HACKTOBERFEST.md)

![video-example-of-docs-gpt](https://d3dg1063dc54p9.cloudfront.net/videos/demov3.gif)


## Roadmap

Explore our roadmap right [here](https://github.com/orgs/arc53/projects/2). Feel free to contribute or raise issues; your input greatly aids in enhancing DocsGPT!

## Our optimized Open-Source models for DocsGPT:

| Name              | Base Model | Requirements (or similar)                        |
|-------------------|------------|----------------------------------------------------------|
| [Docsgpt-7b-falcon](https://huggingface.co/Arc53/docsgpt-7b-falcon)  | Falcon-7b  |  1xA10G gpu   |
| [Docsgpt-14b](https://huggingface.co/Arc53/docsgpt-14b)              | llama-2-14b    | 2xA10 gpu's   |
| [Docsgpt-40b-falcon](https://huggingface.co/Arc53/docsgpt-40b-falcon)       | falcon-40b     | 8xA10G gpu's  |


If you lack sufficient resources to operate it, you can employ bitsnbytes for quantization.


## Features

![Group 9](https://user-images.githubusercontent.com/17906039/220427472-2644cff4-7666-46a5-819f-fc4a521f63c7.png)


## Useful links

 - 🔍🔥 [Live preview](https://docsgpt.arc53.com/)
 
 - 💬🎉[Join our Discord](https://discord.gg/n5BX8dh8rU)
 
 - 📚😎 [Guides](https://docs.docsgpt.co.uk/)

 - 👩‍💻👨‍💻 [Interested in contributing?](https://github.com/arc53/DocsGPT/blob/main/CONTRIBUTING.md)

 - 🗂️🚀 [How to use any other documentation](https://docs.docsgpt.co.uk/Guides/How-to-train-on-other-documentation)

 - 🏠🔐  [How to host it locally (so all data will stay on-premises)](https://docs.docsgpt.co.uk/Guides/How-to-use-different-LLM)




## Project structure

- Application: The Flask app (main application).

- Extensions: The Chrome extension.

- Scripts: A script responsible for creating a similarity search index for other libraries.

- Frontend: The frontend, which utilizes Vite and React.

## Getting Started

Please ensure that you have Docker installed.

If you are using Mac OS or Linux, follow these steps:

`./setup.sh`

This will install all the necessary dependencies and provide the option to either download the local model or utilize OpenAI. 

Alternatively, consult this guide:

1. Download and open this repository with `git clone https://github.com/arc53/DocsGPT.git`
2. In your main directory, establish a `.env` file and configure the environment variable `OPENAI_API_KEY` with your [OpenAI API key](https://platform.openai.com/account/api-keys), and set `VITE_API_STREAMING` to either 'true' or 'false' based on your preference for receiving streaming answers. It should look like this inside:

   ```
   API_KEY=Yourkey
   VITE_API_STREAMING=true
   ```
  See optional environment variables in the [/.env-template](https://github.com/arc53/DocsGPT/blob/main/.env-template) and [/application/.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) files.
  
4. Run [./run-with-docker-compose.sh](https://github.com/arc53/DocsGPT/blob/main/run-with-docker-compose.sh).

5. Navigate to http://localhost:5173 in your web browser.

To stop, just run `Ctrl + C`.





## Development environments

### Spin up mongo and redis
For development, only two containers are used from [docker-compose.yaml](https://github.com/arc53/DocsGPT/blob/main/docker-compose.yaml) (by deleting all services except for Redis and Mongo). 
See file [docker-compose-dev.yaml](./docker-compose-dev.yaml).

Run
```
docker compose -f docker-compose-dev.yaml build
docker compose -f docker-compose-dev.yaml up -d
```

### Run the backend

Ensure you have Python 3.10 or 3.11 installed.

1. Export the necessary environment variables or prepare a `.env` file within the `/application` folder:
   - Copy the contents of[.env_sample](https://github.com/arc53/DocsGPT/blob/main/application/.env_sample) and create `.env` with your OpenAI API token for the `API_KEY` and `EMBEDDINGS_KEY` fields.

    (check out [`application/core/settings.py`](application/core/settings.py) for additional configuration options.)

2. (optional) Create a Python virtual environment:
You can follow the [Python official documentation](https://docs.python.org/3/tutorial/venv.html) for creating virtual environments.

a) On Mac OS and Linux:
```commandline
python -m venv venv
. venv/bin/activate
```
b) On Windows
```commandline
python -m venv venv
 venv/Scripts/activate
```

3. Switch to the `application/` subdir using the command `cd application/` and proceed to install the necessary dependencies for the backend.
```commandline
pip install -r requirements.txt
```
4. Run the app using `flask run --host=0.0.0.0 --port=7091`.
5. Start worker with `celery -A application.app.celery worker -l INFO`.

### Start frontend 

Ensure that your Node version is 16 or a more recent one.

1. Navigate to the [/frontend](https://github.com/arc53/DocsGPT/tree/main/frontend) directory.
2. If you haven't already installed the required packages `husky` and `vite`, please do so. (ignore this step if they are already installed)
```commandline
npm install husky -g
npm install vite -g
```
3. Install dependencies by executing `npm install --include=dev`.
4. Launch the application by running `npm run dev`.


## Contributing
For details on how to get involved, please consult the [CONTRIBUTING.md](CONTRIBUTING.md) document. We encourage the submission of issues, questions, and pull requests, and look forward to your involvement.

## Code Of Conduct
We as members, contributors, and leaders, pledge to make participation in our community a harassment-free experience for everyone, regardless of age, body size, visible or invisible disability, ethnicity, sex characteristics, gender identity and expression, level of experience, education, socio-economic status, nationality, personal appearance, race, religion, or sexual identity and orientation. Please refer to the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) file for more information about contributing.

## Many Thanks To Our Contributors

<a href="[https://github.com/arc53/DocsGPT/graphs/contributors](https://docsgpt.arc53.com/)">
  <img src="https://contrib.rocks/image?repo=arc53/DocsGPT" />
</a>

## License
The source code license is [MIT](https://opensource.org/license/mit/), as described in the [LICENSE](LICENSE) file.

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)
