# DocsGPT 🦖

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

To install the Chrome extension:
1. In the DocsGPT Github repository click on the "Code" button and select "Download ZIP"
2. Unzip the downloaded file to a location you can easily access
3. Open the Google Chrome browser and click on the three dots menu (upper right corner)
4. Select "More Tools" and then "Extensions"
5. Turn on the "Developer mode" switch in the top right corner of the Extensions page
6. Click on the "Load unpacked" button
7. Select the "Chrome" folder where the DocsGPT files have been unzipped (docsgpt-main > extensions > chrome)
8. The extension should now be added to Google Chrome and can be managed on the Extensions page
9. To disable or remove the extension, simply turn off the toggle switch on the extension card or click on the "Remove" button
## Join our community here [Discord](https://discord.gg/guzNA6DSBk)

## [Guides](https://github.com/arc53/docsgpt/wiki)



## [How to use any other documentation](https://github.com/arc53/docsgpt/wiki/How-to-train-on-other-documentation)

Built with [🦜️🔗 LangChain](https://github.com/hwchase17/langchain)

## Roadmap

Good vectorDB scraping/parsing

Load vectors in UI from arc53

better UI

More prompts for other languages

Better parsing

Extensions for firefox

Extensions for Vscode
