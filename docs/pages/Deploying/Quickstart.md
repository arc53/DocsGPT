## Launching Web App
Note: Make sure you have Docker installed

On Mac OS or Linux just write:

`./setup.sh`

It will install all the dependencies and give you an option to download the local model or use OpenAI

Otherwise, refer to this Guide:

1. Open and download this repository with `git clone https://github.com/arc53/DocsGPT.git`.
2. Create a `.env` file in your root directory and set your `API_KEY` with your openai api key.
3. Run `docker-compose build && docker-compose up`.
4. Navigate to `http://localhost:5173/`.

To stop just run `Ctrl + C`.

### Chrome Extension

To install the Chrome extension:

1. In the DocsGPT GitHub repository, click on the "Code" button and select "Download ZIP".
2. Unzip the downloaded file to a location you can easily access.
3. Open the Google Chrome browser and click on the three dots menu (upper right corner).
4. Select "More Tools" and then "Extensions".
5. Turn on the "Developer mode" switch in the top right corner of the Extensions page.
6. Click on the "Load unpacked" button.
7. Select the "Chrome" folder where the DocsGPT files have been unzipped (docsgpt-main > extensions > chrome).
8. The extension should now be added to Google Chrome and can be managed on the Extensions page.
9. To disable or remove the extension, simply turn off the toggle switch on the extension card or click the "Remove" button.
