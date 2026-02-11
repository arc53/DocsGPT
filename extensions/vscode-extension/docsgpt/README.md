# docsgpt README
DocsGPT VS Code Extension integrates DocsGPT AI-powered documentation search and generation directly into Visual Studio Code. This open-source extension helps developers interact with documentation efficiently.

## Features

*   **Seamless Integration**: Adds a dedicated DocsGPT view to your activity bar for easy access.
*   **Conversational AI**: Chat with your DocsGPT agent directly within the VS Code sidebar.
*   **Context-Aware**: Maintains conversation history until you start a new chat.
*   **Simple Setup**: A welcome screen guides you to configure the extension.
*   **Secure API Key Storage**: Your API key is stored securely using the VS Code Secret Storage API.
*   **Easy Configuration**: Use the `DocsGPT: Set DocsGPT API Key` command to set or update your key.
*   **Conversation Management**: Easily start a new chat session with the "Reset Chat" button.

## Requirements

1.  **Visual Studio Code**: Version `1.85.0` or newer.
2.  **DocsGPT API Key**: You need an API key from a DocsGPT instance.
    *   **Cloud**: Go to app.docsgpt.cloud, create an agent, click 'Publish', and copy the generated API key.

## Known Issues
Currently, only the "answer model" of the DocsGPT API is implemented. Support for other features like document management is planned for future releases.

## API Key Security

We take your security seriously. Your DocsGPT API key is stored securely using the official [VS Code Secret Storage API](https://code.visualstudio.com/api/references/vscode-api#SecretStorage). It is **not** stored in plaintext in your settings and is managed by your operating system's credential manager.

Currently implemented the answer model only of docsgpt. 

## Release Notes
