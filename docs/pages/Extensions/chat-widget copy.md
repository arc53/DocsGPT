# Setting up the DocsGPT Widget in Your React Project

## Introduction:
The DocsGPT Widget is a powerful tool that allows you to integrate AI-powered documentation assistance into your web applications. This guide will walk you through the installation and usage of the DocsGPT Widget in your React project. Whether you're building a web app or a knowledge base, this widget can enhance your user experience.

## Installation
First, make sure you have Node.js and npm installed in your project. Then go to your project and install a new dependency: `npm install docsgpt`.

## Usage
In the file where you want to use the widget, import it and include the CSS file:
```js
import { DocsGPTWidget } from "docsgpt";
```


Now, you can use the widget in your component like this :
```jsx
<DocsGPTWidget
  apiHost="https://your-docsgpt-api.com"
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
/>
```
## Props Table for DocsGPT Widget

| **Prop**          | **Type**         | **Default Value**                                           | **Description**                                                                                     |
|--------------------|------------------|-------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| **`apiHost`**      | `string`         | `"https://gptcloud.arc53.com"`                                     | The URL of your DocsGPT API for vector search and chatbot queries.                                 |
| **`apiKey`**       | `string`         | `""`                                                        | Your API key for authentication. Can be left empty if authentication is not required.              |
| **`avatar`**       | `string`         | `"https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png"`   | Specifies the URL of the avatar or image representing the chatbot.                                 |
| **`title`**        | `string`         | `"Get AI assistance"`                                       | Sets the title text displayed in the chatbot interface.                                            |
| **`description`**  | `string`         | `"DocsGPT's AI Chatbot is here to help"`                     | Provides a brief description of the chatbot's purpose or functionality.                            |
| **`heroTitle`**    | `string`         | `"Welcome to DocsGPT !"`                                    | Displays a welcome title when users interact with the chatbot.                                     |
| **`heroDescription`** | `string`     | `"This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources."` | Provides additional introductory text or information about the chatbot's capabilities.             |
| **`theme`**        | `"dark" \| "light"` | `"dark"`                                                  | Allows you to select the theme for the chatbot interface. Accepts `"dark"` or `"light"`.           |
| **`buttonIcon`**   | `string`         | `"https://your-icon"`                                        | Specifies the URL of the icon image for the widget's launch button.                                |
| **`buttonBg`**     | `string`         | `"#222327"`                                                 | Sets the background color of the widget's launch button.                                           |
| **`size`**         | `"small" \| "medium"` | `"medium"`                                              | Sets the size of the widget. Options are `"small"` or `"medium"`.                                  |

---

## Notes
- **Customizing Props:** All properties can be overridden when embedding the widget. For example, you can provide a unique avatar, title, or color scheme to better align with your brand.
- **Default Theme:** The widget defaults to the dark theme unless explicitly set to `"light"`. 
- **API Key:** If the `apiKey` is not required for your application, leave it empty.

This table provides a clear overview of the customization options available for tailoring the DocsGPT widget to fit your application.


## How to use DocsGPTWidget with [Nextra](https://nextra.site/) (Next.js + MDX)
Install your widget as described above and then go to your `pages/` folder and create a new file `_app.js` with the following content:
```js
import { DocsGPTWidget } from "docsgpt";

export default function MyApp({ Component, pageProps }) {
    return (
        <>
            <Component {...pageProps} />
            <DocsGPTWidget selectDocs="local/docsgpt-sep.zip/"/>
        </>
    )
}
```  
## How to use DocsGPTWidget with HTML
```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta http-equiv="X-UA-Compatible" content="ie=edge" />
    <title>HTML + CSS</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <h1>This is a simple HTML + CSS template!</h1>
    <div id="app"></div>
    <!-- Include the widget script from dist/modern or dist/legacy -->
    <script
      src="https://unpkg.com/docsgpt/dist/modern/main.js"
      type="module"
    ></script>
    <script type="module">
      window.onload = function () {
        renderDocsGPTWidget("app", {
          apiKey: "",
          size: "medium",
        });
      };
    </script>
  </body>
</html>
```
To link the widget to your api and your documents you can pass parameters to the renderDocsGPTWidget('div id', { parameters }).
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DocsGPT Widget</title>
  <script src="https://unpkg.com/docsgpt/dist/modern/main.js" type="module"></script>  
</head>
<body>
  <div id="app"></div>
  <!-- Include the widget script from dist/modern or dist/legacy -->
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
        buttonIcon:"https://your-icon",
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

For more information about React, refer to this [link here](https://react.dev/learn)

