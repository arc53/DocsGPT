# DocsGPT react widget

This widget will allow you to embed a DocsGPT assistant in your React app.

## Installation

```bash
npm install  docsgpt
```

## Usage

### React

```javascript
    import { DocsGPTWidget } from "docsgpt-react";

    const App = () => {
      return <DocsGPTWidget />;
    };
```

To link the widget to your api and your documents you can pass parameters to the <DocsGPTWidget /> component.

```javascript
    import { DocsGPTWidget } from "docsgpt-react";

    const App = () => {
      return <DocsGPTWidget
               apiHost="https://gptcloud.arc53.com"
               apiKey=""
               avatar = "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png"
               title = "Get AI assistance"
               description = "DocsGPT's AI Chatbot is here to help"
               heroTitle = "Welcome to DocsGPT !"
               heroDescription="This chatbot is built with DocsGPT and utilises GenAI, 
               please review important information using sources."
               theme = "dark"
               buttonIcon = "https://your-icon"
               buttonBg = "#222327"
          />;
    };
```

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
        <!-- Include the widget script from dist/modern or dist/legacy -->
        <script src="https://unpkg.com/docsgpt/dist/modern/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('app');
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
        <!-- Include the widget script from dist/modern or dist/legacy -->
        <script src="https://unpkg.com/docsgpt/dist/modern/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('app', {
              apiHost: 'http://localhost:7001',
              apiKey:"",
              avatar: 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
              title: 'Get AI assistance',
              description: "DocsGPT's AI Chatbot is here to help",
              heroTitle: 'Welcome to DocsGPT!',
              heroDescription: 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.',
              theme:"dark",
              buttonIcon:"https://your-icon.svg",
              buttonBg:"#222327"
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
import { SearchBar } from "docsgpt-react";
```

---

### Usage Example
```tsx
<SearchBar 
    apiKey="your-api-key"
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
  <script src="https://unpkg.com/docsgpt/dist/modern/main.js"></script> <!-- The bundled JavaScript file -->
</head>
<body>
  <!-- Element where the SearchBar will render -->
  <div id="search-bar-container"></div>

  <script>
    // Render the SearchBar into the specified element
    renderSearchBar('search-bar-container', {
      apiKey: 'your-api-key-here',
      apiHost: 'https://your-api-host.com',
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
| **`apiKey`**    | `string`  | `"74039c6d-bff7-44ce-ae55-2973cbf13837"` | Your API key generated from the app. Used for authenticating requests.                         |
| **`apiHost`**   | `string`  | `"https://gptcloud.arc53.com"`       | The base URL of the server hosting the vector similarity search and chatbot services.           |
| **`theme`**     | `"dark" \| "light"` | `"dark"`                            | The theme of the search bar. Accepts `"dark"` or `"light"`.                                     |
| **`placeholder`** | `string` | `"Search or Ask AI..."`             | Placeholder text displayed in the search input field.                                           |
| **`width`**     | `string`  | `"256px"`                          | Width of the search bar. Accepts any valid CSS width value (e.g., `"300px"`, `"100%"`, `"20rem"`). |


Feel free to reach out if you need help customizing or extending the `SearchBar`!

## Our github

[DocsGPT](https://github.com/arc53/DocsGPT)

You can find the source code in the extensions/react-widget folder.
