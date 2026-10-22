# DocsGPT react widget

This widget will allow you to embed a DocsGPT assistant in your React app.

## Installation

```bash
npm install docsgpt
```

The same React components are also published as `docsgpt-react`, a React-only build without the HTML embedding bundle. If you install that package instead, import from `"docsgpt-react"`.

Every example below needs the API key of a published DocsGPT agent. See [Agent API keys](https://docs.docsgpt.cloud/API/agent-keys). If you leave `apiKey` out, the chat widget answers from a public DocsGPT demo agent instead of your documents, and the search bar searches that demo agent. Full props reference: [chat widget](https://docs.docsgpt.cloud/Extensions/chat-widget) and [search widget](https://docs.docsgpt.cloud/Extensions/search-widget).

## Usage

### React

```javascript
    import { DocsGPTWidget } from "docsgpt";

    const App = () => {
      return <DocsGPTWidget apiKey="your-agent-api-key" />;
    };
```

To link the widget to your api and your documents you can pass parameters to the <DocsGPTWidget /> component.

```javascript
    import { DocsGPTWidget } from "docsgpt";

    const App = () => {
      return <DocsGPTWidget
               apiHost="https://gptcloud.arc53.com"
               apiKey="your-agent-api-key"
               avatar = "https://your-cdn/avatar.png"
               title = "Get AI assistance"
               description = "DocsGPT's AI Chatbot is here to help"
               heroTitle = "Welcome to DocsGPT !"
               heroDescription="This chatbot is built with DocsGPT and utilises GenAI, 
               please review important information using sources."
               theme = "dark"
               buttonIcon = "https://your-icon"
               buttonBg = "#222327"
               allowedFileExtensions = {['.pdf', '.docx', '.md', '.png']}
               showMicButton
               suggestedQuestions = {['How do I get started?', 'Which plans include SSO?']}
          />;
    };
```

`avatar` sets the header image and `heroIcon` the image on the welcome card (the DocsGPT mark by default). `poweredBy` controls the credit line under the input: `false` hides it, and `{ label, href }` replaces it.

`suggestedQuestions` lists questions under the welcome card; a click sends one, and the list goes away once the conversation starts. `suggestedQuestionsLabel` sets the heading over them ("Suggested questions" by default; an empty string hides it).

The widget's own text follows the visitor's browser language (`locale="auto"`, the default) in English, Spanish, French, Japanese, Simplified and Traditional Chinese, Russian and German. Set `locale` (e.g. `"de"`) to fix it, and `translations` to replace single strings by key, e.g. `translations={{ composerPlaceholder: 'Ask our team' }}`. Text you pass in props such as `title` is never translated. The keys are in [`src/locale/en.ts`](src/locale/en.ts); `SearchBar` takes the same two props. See [Languages](https://docs.docsgpt.cloud/Extensions/chat-widget#languages).

Pass a `ref` to drive the widget from your page (`open()`, `close()`, `toggle()`, `isOpen()`, `focus()`, `ask(question, { send })`, `newChat()`, `clearHistory()`, and `on`/`off` for events), and `onEvent` to receive every event, e.g. `question_submitted`, `answer_completed` or `feedback`. With the script tag, `renderDocsGPTWidget` returns the same controller plus `destroy()`, and `renderSearchBar` returns `{ destroy }`. See [JavaScript API](https://docs.docsgpt.cloud/Extensions/chat-widget#javascript-api).

Conversations are kept in the visitor's `localStorage` (per agent, the 30 most recent), so a reload continues the chat, and the header has **New chat** and **Chat history** buttons. Set `persistConversations={false}` to store nothing, and call `clearHistory()` on logout where computers are shared. See [Conversation history](https://docs.docsgpt.cloud/Extensions/chat-widget#conversation-history).

Set `layout="sidebar"` to dock the chat to the edge of the window at full height instead of floating it above the button. `sidebarSide` picks the edge (`'right'` by default) and `sidebarWidth` the starting width (420px). Visitors can drag the inner edge, or use the arrow keys on it, to resize it between 320px and `min(720px, 70vw)`, and their width is remembered unless `persistConversations` is false. `size` doesn't apply to the sidebar, and on phones it opens full screen. See [Sidebar layout](https://docs.docsgpt.cloud/Extensions/chat-widget#sidebar-layout).

`allowedFileExtensions` and `showMicButton` are both off unless you set them. Attached files are parsed and billed against your key's token budget, and the microphone uses the browser's Web Speech API, which forwards audio to the browser vendor's speech service outside on-device Chromium builds. See [the widget docs](https://docs.docsgpt.cloud/Extensions/chat-widget) for details and browser support.

### Html

```html
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta http-equiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>DocsGPT Widget</title>
      </head>
      <body>
        <div id="app"></div>
        <script src="https://unpkg.com/docsgpt@0.13.0/dist/legacy/browser.js"></script>
        <script>
          window.onload = function() {
            renderDocsGPTWidget('app', { apiKey: 'your-agent-api-key' });
          }
        </script>
      </body>
    </html>
```

To link the widget to your api and your documents you can pass parameters to the **renderDocsGPTWidget('div id', { parameters })**.

```html
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta http-equiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>DocsGPT Widget</title>
      </head>
      <body>
        <div id="app"></div>
        <script src="https://unpkg.com/docsgpt@0.13.0/dist/legacy/browser.js"></script>
        <script>
          window.onload = function() {
            renderDocsGPTWidget('app', {
              apiHost: 'http://localhost:7091',
              apiKey: 'your-agent-api-key',
              avatar: 'https://your-cdn/avatar.png',
              title: 'Get AI assistance',
              description: "DocsGPT's AI Chatbot is here to help",
              heroTitle: 'Welcome to DocsGPT!',
              heroDescription: 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
              theme:"dark",
              buttonIcon:"https://your-icon.svg",
              buttonBg:"#222327",
              allowedFileExtensions: ['.pdf', '.docx', '.md', '.png'],
              showMicButton: true,
              suggestedQuestions: ['How do I get started?', 'Which plans include SSO?']
            });
          }
        </script>
      </body>
    </html>
```

# SearchBar

The `SearchBar` component is an interactive search bar designed to provide search results based on **vector similarity search**. It also includes the capability to open the AI Chatbot, enabling users to query.

---

### Importing the Component
```tsx
import { SearchBar } from "docsgpt";
```

---

### Usage Example
```tsx
<SearchBar 
    apiKey="your-agent-api-key"
    apiHost="https://gptcloud.arc53.com"
    theme="light"
    placeholder="Search or Ask AI..."
    width="300px"
/>
```

---

## HTML embedding for Search bar

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SearchBar Embedding</title>
  <script src="https://unpkg.com/docsgpt@0.13.0/dist/legacy/browser.js"></script> <!-- The bundled JavaScript file -->
</head>
<body>
  <!-- Element where the SearchBar will render -->
  <div id="search-bar-container"></div>

  <script>
    // Render the SearchBar into the specified element
    renderSearchBar('search-bar-container', {
      apiKey: 'your-agent-api-key',
      apiHost: 'https://gptcloud.arc53.com',
      theme: 'light',
      placeholder: 'Search here...',
      width: '300px'
    });
  </script>
</body>
</html>

```

### Props

| **Prop**       | **Type**  | **Default Value**                   | **Description**                                                                                  |
|-----------------|-----------|-------------------------------------|--------------------------------------------------------------------------------------------------|
| **`apiKey`**    | `string`  | a DocsGPT demo agent's key | Required. The API key of your published agent. An omitted key searches a public DocsGPT demo agent; an empty key is rejected. |
| **`apiHost`**   | `string`  | `"https://gptcloud.arc53.com"`       | The base URL of the server hosting the vector similarity search and chatbot services.           |
| **`theme`**     | `"dark" \| "light"` | `"dark"`                            | The theme of the search bar. Accepts `"dark"` or `"light"`.                                     |
| **`placeholder`** | `string` | `"Search or Ask AI..."`             | Placeholder text displayed in the search input field. The default follows `locale`.             |
| **`width`**     | `string`  | `"256px"`                          | Width of the search bar. Accepts any valid CSS width value (e.g., `"300px"`, `"100%"`, `"20rem"`). |
| **`buttonText`** | `string` | `"Search here"`                     | Text in the search field on the page: the button label (`modal`) or the field's placeholder (`dropdown`). The default follows `locale`. |
| **`variant`**   | `"modal" \| "dropdown"` | `"modal"` | `modal` opens a search dialog from a button; `dropdown` is a field you type into, with results in a panel under it. |
| **`shape`**     | `"pill" \| "rounded"` | `"pill"` | Corners of the search field: fully rounded, or 8px. |
| **`avatar`**    | `string`  | a person on the brand-colour circle | Image beside "Ask the AI", also used by the chat it opens. |
| **`poweredBy`** | `boolean \| { label, href? }` | `true` | Credit line under the results: `false` hides it, an object replaces it. |
| **`allowedFileExtensions`** | `string[]` | _unset_ | Passed to the chat opened from "Ask the AI". File extensions its composer accepts, e.g. `['.pdf', '.md']`; attachments stay off while unset. |
| **`showMicButton`** | `boolean` | `false` | Adds a microphone to the search field for dictating a query, and passes the same option to the chat opened from "Ask the AI". Uses the browser's Web Speech API. |
| **`passthrough`** | `Record<string, string \| number \| boolean \| null>` | _unset_ | Passed to the chat opened from "Ask the AI": values sent with every question, such as the signed-in user's id. The agent's prompt reads them as `{{ passthrough.user_id }}` and they appear in the agent's Logs. |
| **`locale`** | `string` | `"auto"` | Language of the search bar's text and the chat it opens: `"auto"` (the browser's), or `en`, `es`, `fr`, `ja`, `zh`, `zh-TW`, `ru`, `de`. |
| **`translations`** | `Partial<Messages>` | _unset_ | Replaces single strings by key, e.g. `{ askTheAi: 'Ask our assistant' }`. |
| **`onEvent`** | `(event) => void` | _unset_ | Passed to the chat opened from "Ask the AI": called with each of its events. |


Feel free to reach out if you need help customizing or extending the `SearchBar`!

## Our github

[DocsGPT](https://github.com/arc53/DocsGPT)

You can find the source code in the extensions/react-widget folder.
