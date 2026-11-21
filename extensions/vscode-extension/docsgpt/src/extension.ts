import * as vscode from "vscode";
import fetch from "node-fetch";

// Helper function to generate a random nonce for Content Security Policy
function getNonce() {
  let text = '';
  const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

export function activate(context: vscode.ExtensionContext) {
  console.log("✅ DocsGPT Code Assist: extension activated!");

  // Register the sidebar view provider
  const provider = new DocsGPTViewProvider(context.extensionUri, context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("docsgptView", provider)
  );

  console.log("DocsGPTViewProvider registered.");
  vscode.commands.executeCommand("workbench.view.extension.docsgpt-sidebar");

  // Command: set DocsGPT API key
  context.subscriptions.push(
    vscode.commands.registerCommand("docsgpt.setApiKey", async () => {
      const apiKey = await vscode.window.showInputBox({
        title: "DocsGPT API Key",
        prompt: "Create an agent, click 'Publish', and paste the generated API key here.",
        ignoreFocusOut: true,
        password: true,
      });
      if (apiKey) {
        await context.secrets.store("docsgptApiKey", apiKey);
        vscode.window.showInformationMessage("DocsGPT API key saved!");
        // Refresh the webview to show the chat interface and reset the conversation context
        provider.resetConversation();
        provider.refresh();
      }
    })
  );

  // Command: manually open panel (for activation testing)
  context.subscriptions.push(
    vscode.commands.registerCommand("docsgpt.openPanel", async () => {
      vscode.commands.executeCommand("workbench.view.extension.docsgpt-sidebar");
    })
  );
}

class DocsGPTViewProvider implements vscode.WebviewViewProvider {
  private _view?: vscode.WebviewView;
  private _conversationId?: string;

  constructor(private readonly _extensionUri: vscode.Uri, private readonly _context: vscode.ExtensionContext) {}

  public async resolveWebviewView(webviewView: vscode.WebviewView, context: vscode.WebviewViewResolveContext, _token: vscode.CancellationToken) {
    console.log("DocsGPT webview is being resolved!");
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri],
    };

    // Load HTML UI into the sidebar webview
    const apiKey = await this._context.secrets.get('docsgptApiKey');
    webviewView.webview.html = this._getHtml(webviewView.webview, !!apiKey);

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage((message) => {
      if (!this._view) return;

      if (message.command === "login") {
        const apiUrl = vscode.workspace.getConfiguration('docsgpt').get<string>('apiUrl') || 'https://app.docsgpt.cloud';
        vscode.env.openExternal(vscode.Uri.parse(apiUrl));
      } else if (message.command === "enterApiKey") {
        // Trigger the command to ask for the API key
        vscode.commands.executeCommand("docsgpt.setApiKey");
      } else if (message.command === "sendMessage") { // Make this block async
        const userMessage = message.text;
        console.log(`💬 User message: ${userMessage}`);
        this.getApiResponse(userMessage);
      } else if (message.command === "newChat") {
        this.resetConversation();
        // We can also clear the webview history here
        this._view.webview.postMessage({ command: 'clearChat' });
      }
    });
  }

// This is the corrected function
private async getApiResponse(userMessage: string) {
    if (!this._view) {
      return;
    }

    const apiKey = await this._context.secrets.get('docsgptApiKey');
    if (!apiKey) {
      this._view.webview.postMessage({ command: 'addMessage', text: 'API Key not set. Please set it using the "Set DocsGPT API Key" command.' });
      return;
    }

    // Show a loading indicator in the webview
    this._view.webview.postMessage({ command: 'showLoading' });

    try {
      const apiUrl = 'https://gptcloud.arc53.com';

      //endpoint
      const url = `${apiUrl}/api/answer`; 

      // AnswerModel
      const bodyData: any = {
        question: userMessage,
        api_key: apiKey,
      };

      if (this._conversationId) {
        bodyData.conversation_id = this._conversationId;
      }
      
      //Make the request using POST and send the data in the body
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json", 
        },
        body: JSON.stringify(bodyData),
      });

      if (!response.ok) {
        const errorBody = await response.text();
        console.error(`API Error: ${response.status} ${response.statusText}`, errorBody);
        throw new Error(`API request failed with status ${response.status}`);
      }

      // valid JSON response
      const data: any = await response.json();

      if (data.conversation_id) {
        this._conversationId = data.conversation_id;
        console.log(`Conversation ID set to: ${this._conversationId}`);
      }

      const botResponse = data.answer || "Sorry, I couldn't get a response.";
      this._view.webview.postMessage({
        command: 'addBotMessage',
        text: botResponse
      });

    } catch (error) {
      console.error("Error calling DocsGPT API:", error);
      this._view.webview.postMessage({ command: 'addBotMessage', text: "Sorry, something went wrong while connecting to the API." });
    }
  }

  // Method to reset the conversation
  public resetConversation() {
    this._conversationId = undefined;
    console.log("Conversation context has been reset.");
  }

  // Method to refresh the webview content
  public async refresh() {
    if (this._view) {
      const apiKey = await this._context.secrets.get('docsgptApiKey');
      this._view.webview.html = this._getHtml(this._view.webview, !!apiKey);
    }
  }

  private _getHtml(webview: vscode.Webview, hasApiKey: boolean): string {
    const nonce = getNonce();

    const style = `
      <style>
        body, html {
          height: 100%;
          margin: 0;
          padding: 0;
          overflow: hidden;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
          color: var(--vscode-editor-foreground);
          background-color: var(--vscode-side-bar-background);
        }
        .container { display: none; height: 100%; flex-direction: column; }
        .container.active { display: flex; }
        .chat-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 0.5rem 1rem;
          border-bottom: 1px solid var(--vscode-editor-widget-border);
        }
        .chat-header span {
          font-weight: bold;
        }
        #changeApiKeyBtn, #newChatBtn {
          background: none; border: none; cursor: pointer; font-size: 1.2rem; padding: 0; margin: 0; color: var(--vscode-icon-foreground);
        }
        #changeApiKeyBtn {
          margin-left: 0.5rem;
        }
        .setup-container { text-align: center; padding: 1rem; }
        .chat-messages { flex-grow: 1; overflow-y: auto; padding: 1rem; }
        .message { padding: 0.6rem 1rem; border-radius: 1rem; margin-bottom: 0.5rem; max-width: 80%; word-wrap: break-word; }
        .user-message { background-color: var(--vscode-list-active-selection-background); color: var(--vscode-list-active-selection-foreground); align-self: flex-end; margin-left: auto; }
        .bot-message { background-color: var(--vscode-editor-widget-background); border: 1px solid var(--vscode-editor-widget-border); align-self: flex-start; }
        .chat-input-form { display: flex; padding: 0.5rem; border-top: 1px solid var(--vscode-editor-widget-border); }
        #chat-input { flex-grow: 1; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border); border-radius: 4px; padding: 0.5rem; resize: none; }
        button {
          background: var(--vscode-button-background);
          color: var(--vscode-button-foreground);
          border: 1px solid var(--vscode-button-border, transparent);
          border-radius: 4px;
          cursor: pointer;
          margin-left: 0.5rem;
          padding: 0.5rem 1rem;
        }
        .setup-container button { margin-top: 1rem; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        h2 { color: var(--vscode-textLink-foreground); }
        p { font-size: 13px; opacity: 0.9; }
        hr { border: 1px solid var(--vscode-editorWidget-border); margin: 2rem 0; }
      </style>
    `;

    return `
      <!DOCTYPE html>
      <html lang="en">
        <head>
          <meta charset="UTF-8" />
          <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          ${style}
        </head>
        <body>
          <div id="setup-view" class="container ${!hasApiKey ? 'active' : ''}">
            <div class="setup-container">
              <h2>Welcome to DocsGPT</h2>
              <p>To get an API key, create an agent and click 'Publish' on the DocsGPT website.</p>
              <button id="login">Open DocsGPT</button>
              <hr />
              <p>Once you have your key, enter it below.</p>
              <button id="enterApiKey">Enter API Key</button>
            </div>
          </div>

          <div id="chat-view" class="container ${hasApiKey ? 'active' : ''}">
            <div class="chat-header">
              <span>DocsGPT</span>
              <div>
                <button id="newChatBtn" title="Reset Chat">↻</button>
                <button id="changeApiKeyBtn" title="Change API Key">⛯</button>
              </div>
            </div>
            <div class="chat-messages" id="chat-messages">
              <div class="message bot-message">Hello! How can I help you today?</div>
            </div>
            <form class="chat-input-form" id="chat-input-form">
              <textarea id="chat-input" placeholder="Ask DocsGPT..." rows="1"></textarea>
              <button type="submit">Send</button>
            </form>
          </div>

          <script nonce="${nonce}">
            const vscode = acquireVsCodeApi();

            // Setup View listeners
            document.getElementById('login').addEventListener('click', () => {
              vscode.postMessage({ command: 'login' });
            });
            document.getElementById('enterApiKey').addEventListener('click', () => {
              vscode.postMessage({ command: 'enterApiKey' });
            });

            document.getElementById('newChatBtn').addEventListener('click', () => {
              vscode.postMessage({ command: 'newChat' });
            });

            document.getElementById('changeApiKeyBtn').addEventListener('click', () => {
              vscode.postMessage({ command: 'enterApiKey' });
            });

            // Chat View listeners
            const chatMessages = document.getElementById('chat-messages');
            const form = document.getElementById('chat-input-form');
            const input = document.getElementById('chat-input');

            function addMessage(text, type) {
              const messageDiv = document.createElement('div');
              messageDiv.className = 'message ' + type + '-message';
              messageDiv.textContent = text;
              chatMessages.appendChild(messageDiv);
              chatMessages.scrollTop = chatMessages.scrollHeight;
              return messageDiv;
            }

            function removeLoadingIndicator() {
              const loading = document.getElementById('loading-indicator');
              if (loading) {
                loading.remove();
              }
            }

            form.addEventListener('submit', (e) => {
              e.preventDefault();
              const messageText = input.value.trim();
              if (messageText) {
                addMessage(messageText, 'user');
                vscode.postMessage({ command: 'sendMessage', text: messageText });
                input.value = '';
              }
            });

            window.addEventListener('message', event => {
              const message = event.data;
              switch (message.command) {
                case 'addBotMessage':
                  removeLoadingIndicator();
                  addMessage(message.text, 'bot');
                  break;
                case 'showLoading':
                  addMessage('Thinking...', 'bot').id = 'loading-indicator';
                  break;
                case 'clearChat':
                  chatMessages.innerHTML = '';
                  addMessage('Hello! How can I help you today?', 'bot');
                  break;
              }
            });
          </script>
        </body>
      </html>
    `;
  }
}

export function deactivate() {
  console.log("DocsGPT Code Assist deactivated.");
}
