<p align="center">
  <img src="./Readme Logo.png">
</p>



<p align="center">
  <strong>DocsGPT - Simplifying Project Documentation with AI-powered Assistance</strong>
</p>

<p align="left">
  <strong>DocsGPT</strong> is a cutting-edge open-source solution that streamlines the process of finding information in project documentation. With its integration of the powerful <strong>GPT</strong> engine, developers can easily ask questions about a project and receive accurate answers.
  
Say goodbye to time-consuming manual searches, and let <strong>DocsGPT</strong> help you quickly find the information you need. Try it out and see how it revolutionizes your project documentation experience. Contribute to its development and be a part of the future of AI-powered assistance.
</p>


## What is DocsGPT
The aim of DocsGPT is to utilize the GPT engine to answer questions about the documentation of any project, making it easier for developers to find the information they need .

Screenshot <img width="1440" alt="image" src="https://user-images.githubusercontent.com/15183589/216717215-adc6ea2d-5b35-4694-ac0d-e39a396025f4.png">

## [Live preview](https://docsgpt.arc53.com/)


## Project structure
application - flask app (main application)

extensions - chrome extension

scripts - script that creates similarity search index and store for other libraries 

## QuickStart
Please note: current vector database uses pandas Python documentation, thus responses will be related to it, if you want to use other docs please follow a guide below

1. Navigate to `/application` folder
2. Install dependencies
`pip install -r requirements.txt`
3. Prepare .env file
Copy .env_sample and create .env with your openai api token
4. Run the app
`python app.py`


[To install the Chrome extension](https://github.com/arc53/docsgpt/wiki#launch-chrome-extension)


## [Guides](https://github.com/arc53/docsgpt/wiki)



## [How to use any other documentation](https://github.com/arc53/docsgpt/wiki/How-to-train-on-other-documentation)

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)

## Roadmap

- Good vectorDB scraping/parsing
- Load vectors in UI from arc53
- Better UI
- More prompts for other languages
- Better parsing
- Extensions for firefox
- Extensions for Vscode

