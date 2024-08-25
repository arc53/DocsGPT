### Setting up the DocsGPT Widget in Your React Project

### Introduction:
The DocsGPT Widget is a powerful tool that allows you to integrate AI-powered documentation assistance into your web applications. This guide will walk you through the installation and usage of the DocsGPT Widget in your React project. Whether you're building a web app or a knowledge base, this widget can enhance your user experience.

### Installation
First, make sure you have Node.js and npm installed in your project. Then go to your project and install a new dependency: `npm install docsgpt`.

### Usage
In the file where you want to use the widget, import it and include the CSS file:
```js
import { DocsGPTWidget } from "docsgpt";
```


Now, you can use the widget in your component like this :
```jsx
<DocsGPTWidget
  apiHost="https://your-docsgpt-api.com"
  apiKey=""
  avatar = "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png",
  title = "Get AI assistance",
  description = "DocsGPT's AI Chatbot is here to help",
  heroTitle = "Welcome to DocsGPT !",
  heroDescription="This chatbot is built with DocsGPT and utilises GenAI, 
  please review important information using sources."
  theme = "dark"
  buttonIcon = "https://your-icon"
  buttonBg = "#222327"
/>
```
DocsGPTWidget takes 8 **props** with default fallback values:
1. `apiHost` — The URL of your DocsGPT API.
2. `theme` — Allows to select your specific theme (dark or light).
3. `apiKey` — Usually, it's empty.
4. `avatar`: Specifies the URL of the avatar or image representing the chatbot.
5. `title`: Sets the title text displayed in the chatbot interface.
6. `description`: Provides a brief description of the chatbot's purpose or functionality.
7. `heroTitle`: Displays a welcome title when users interact with the chatbot.
8. `heroDescription`: Provide additional introductory text or information about the chatbot's capabilities.
9. `buttonIcon`: Specifies the url of the icon image for the widget.
10. `buttonBg`: Allows to specify the Background color of the widget.
11. `size`: Sets the size of the widget ( small, medium).


### How to use DocsGPTWidget with [Nextra](https://nextra.site/) (Next.js + MDX)
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
### How to use DocsGPTWidget with HTML
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
        theme:"dark"
        buttonIcon:"https://your-icon",
        buttonBg:"#222327"
      });
    }
  </script>
</body>
</html>
```

For more information about React, refer to this [link here](https://react.dev/learn)

