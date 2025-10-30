import * as vscode from "vscode";
import axios from "axios";
import MarkdownIt from "markdown-it";

/**
 * Called when the extension is activated
 */
export function activate(context: vscode.ExtensionContext) {
  vscode.window.showInformationMessage("DocsGPT extension activated!");
  console.log("✅ DocsGPT extension activated!");

  const provider = new DocsGPTViewProvider(context.extensionUri);

  // ✅ This registers the sidebar and binds onDidReceiveMessage correctly
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("docsgptView", provider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  // Optional manual command to focus the sidebar
  const openViewCmd = vscode.commands.registerCommand("docsgpt.openView", async () => {
    await vscode.commands.executeCommand("workbench.view.extension.docsgpt");
  });

  context.subscriptions.push(openViewCmd);

  console.log("📦 Container ID: docsgpt");
  console.log("🪟 View ID registered: docsgptView");

}


/**
 * The Webview Provider that powers the DocsGPT sidebar
 */
class DocsGPTViewProvider implements vscode.WebviewViewProvider {
  private md: MarkdownIt;

  constructor(private readonly extensionUri: vscode.Uri) {
    this.md = new MarkdownIt();
  }

  /**
   * Called when the webview view is resolved (visible)
   */
  public resolveWebviewView(webviewView: vscode.WebviewView) {
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this.getHtml(webviewView.webview);

    // Handle messages from the webview
    webviewView.webview.onDidReceiveMessage(async (message) => {
      if (message.command === "ask") {
        console.log("📩 Received message from webview:", message);
        // 1. Read configuration from VS Code settings
        const config = vscode.workspace.getConfiguration('docsgpt');
        const apiUrl = config.get<string>('apiUrl');
        const apiKey = config.get<string>('apiKey')?.trim();

        if (!apiUrl) {
          // This should not happen if the default is set, but it's good practice
          vscode.window.showErrorMessage("DocsGPT API URL is not configured.");
          return;
        }
        

        const question = message.text.trim();
        if (!question) {
          vscode.window.showErrorMessage("Please enter a question.");
          return;
        }

        try {
          // 2. Prepare the API request
          const requestConfig: axios.AxiosRequestConfig = {};
          if (apiKey) {
            requestConfig.headers = {
              "Authorization": `Bearer ${apiKey}`
            };
          }

          // 3. Call the API
          const response = await axios.post(
            apiUrl,
            { // Payload (data)
              question,
              prompt_id: "default",
              chunks: 2,
              save_conversation: false,
            },
            requestConfig
          );

          const rawAnswer = response.data?.answer || "No answer returned.";
          const htmlAnswer = this.md.render(rawAnswer);
          webviewView.webview.postMessage({ command: "answer", htmlAnswer: htmlAnswer });
        } catch (error: any) {
          let msg = error.message || "Unknown error";
          // Give a helpful error if the key is wrong
          if (error.response?.status === 401 || error.response?.status === 403) {
            msg = "Authentication failed. Is your API Key correct?";
          }
          webviewView.webview.postMessage({
            command: "answer",
            htmlAnswer: `<p>⚠️ Error fetching from DocsGPT API: ${msg}</p>`,
          });
        }
      }
    });
  }

  /**
   * HTML for the sidebar webview
   */
  public getHtml(webview: vscode.Webview): string {
    const nonce = getNonce();

    return /* html */ `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <style>
          body {
            font-family: sans-serif;
            padding: 10px;
            color: var(--vscode-editor-foreground);
            background-color: var(--vscode-sideBar-background);
          }
          input, button {
            font-size: 14px;
            margin: 5px 0;
            border-radius: 4px;
            border: 1px solid var(--vscode-input-border);
            color: var(--vscode-input-foreground);
            background-color: var(--vscode-input-background);
          }
          input {
            width: 80%;
            padding: 6px;
          }
          button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            padding: 6px 10px;
            cursor: pointer;
          }
          button:hover {
            background-color: var(--vscode-button-hoverBackground);
          }
          #messages {
            display: flex;
            flex-direction: column;
          }
          .message {
            padding: 8px 12px;
            border-radius: 12px;
            margin-bottom: 8px;
            max-width: 80%;
            word-wrap: break-word;
          }
          #answer {
            margin-top: 15px;
            border-top: 1px solid var(--vscode-editor-foreground);
            padding-top: 10px;
          }
          #answer pre {
            background-color: var(--vscode-editor-background);
            padding: 10px;
            border-radius: 5px;
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-x: auto;
          }
          #answer code {
            font-family: var(--vscode-editor-font-family);
          }
          #answer a {
            color: var(--vscode-textLink-foreground);
          }
          #answer a:hover {
            color: var(--vscode-textLink-activeForeground);
          }
          h3 {
            margin-bottom: 10px;
            color: var(--vscode-sideBar-titleForeground);
          }
        </style>
      </head>
      <body>
        <h3>Ask DocsGPT</h3>
        <input id="q" placeholder="Ask a question..." />
        <button onclick="ask()">Ask</button>
        <div id="messages"></div>

        <script nonce="${nonce}">
          const vscode = acquireVsCodeApi();
          const inputEl = document.getElementById('q');
          const messagesEl = document.getElementById('messages');

          function ask() {
            const text = inputEl.value;
            if (!text) return;

            // Display user's question
            const userMessage = document.createElement('div');
            userMessage.className = 'message';
            userMessage.style.alignSelf = 'flex-end';
            userMessage.style.backgroundColor = 'var(--vscode-button-background)';
            userMessage.textContent = text;
            messagesEl.appendChild(userMessage);

            // Display thinking indicator
            const thinkingMessage = document.createElement('div');
            thinkingMessage.id = 'thinking';
            thinkingMessage.className = 'message';
            thinkingMessage.style.alignSelf = 'flex-start';
            thinkingMessage.innerHTML = '<p>Thinking...</p>';
            messagesEl.appendChild(thinkingMessage);

            inputEl.value = ''; // Clear input
            vscode.postMessage({ command: 'ask', text });
          }

          // Add event listener for the 'Enter' key on the input field
          inputEl.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') {
              ask();
            }
          });

          window.addEventListener('message', event => {
            const msg = event.data;
            if (msg.command === 'answer') {
              const thinkingEl = document.getElementById('thinking');
              if (thinkingEl) {
                // Replace "Thinking..." with the actual answer
                thinkingEl.id = ''; // remove id to prevent it from being selected again
                thinkingEl.innerHTML = msg.htmlAnswer;
              }
              // Scroll to the bottom
              window.scrollTo(0, document.body.scrollHeight);
            }
          });
        </script>
      </body>
      </html>
    `;
  }
}

/* Generates a random nonce for the webview CSP */
function getNonce() {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

export function deactivate() {}