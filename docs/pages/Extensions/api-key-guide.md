## Guide to DocsGPT API Keys

DocsGPT API keys are essential for developers and users who wish to integrate the  DocsGPT models into external applications, such as the our widget. This guide will walk you through the steps of obtaining an API key, starting from uploading your document to understanding the key variables associated with API keys.

### Uploading Your Document

Before creating your first API key, you must upload the document that will be linked to this key. You can upload your document through two methods:

- **GUI Web App Upload:** A user-friendly graphical interface that allows for easy upload and management of documents.
- **Using `/api/upload` Method:** For users comfortable with API calls, this method provides a direct way to upload documents.

### Obtaining Your API Key

After uploading your document, you can obtain an API key either through the graphical user interface or via an API call:

- **Graphical User Interface:** Navigate to the Settings section of the DocsGPT web app, find the API Keys option, and press 'Create New' to generate your key.
- **API Call:** Alternatively, you can use the `/api/create_api_key` endpoint to create a new API key. For detailed instructions, visit [DocsGPT API Documentation](https://docs.docsgpt.co.uk/Developing/API-docs#8-apicreate_api_key).

### Understanding Key Variables

Upon creating your API key, you will encounter several key variables. Each serves a specific purpose:

- **Name:** Assign a name to your API key for easy identification.
- **Source:** Indicates the source document(s) linked to your API key, which DocsGPT will use to generate responses.
- **ID:** A unique identifier for your API key. You can view this by making a call to `/api/get_api_keys`.
- **Key:** The API key itself, which will be used in your application to authenticate API requests.

With your API key ready, you can now integrate DocsGPT into your application, such as the DocsGPT Widget or any other software, via `/api/answer` or `/stream` endpoints. The source document is preset with the API key, allowing you to bypass fields like `selectDocs` and `active_docs` during implementation.

Congratulations on taking the first step towards enhancing your applications with DocsGPT! With this guide, you're now equipped to navigate the process of obtaining and understanding DocsGPT API keys.