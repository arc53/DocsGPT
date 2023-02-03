# DocsGPT 🦖

## What is DocsGPT
The aim of DocsGPT is to utilize the GPT engine to answer questions about the documentation of any project, making it easier for developers to find the information they need .

Screenshot <img width="1440" alt="image" src="https://user-images.githubusercontent.com/15183589/216717215-adc6ea2d-5b35-4694-ac0d-e39a396025f4.png">


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
## Join our community here [Discord](https://discord.gg/guzNA6DSBk)

## [Guides](https://github.com/arc53/docsgpt/wiki)



## [How to use any other documentation](https://github.com/arc53/docsgpt/wiki/How-to-train-on-other-documentation)

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)
