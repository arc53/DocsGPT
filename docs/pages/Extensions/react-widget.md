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
  selectDocs="local/docs.zip"
  apiKey=""
  avatar = "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png",
  title = "Get AI assistance",
  description = "DocsGPT's AI Chatbot is here to help",
  heroTitle = "Welcome to DocsGPT !",
  heroDescription="This chatbot is built with DocsGPT and utilises GenAI, 
  please review important information using sources."
/>
```
DocsGPTWidget takes 8 **props** with default fallback values:
1. `apiHost` — The URL of your DocsGPT API.
2. `selectDocs` — The documentation source that you want to use for your widget (e.g. `default` or `local/docs1.zip`).
3. `apiKey` — Usually, it's empty.
4. `avatar`: Specifies the URL of the avatar or image representing the chatbot.
5. `title`: Sets the title text displayed in the chatbot interface.
6. `description`: Provides a brief description of the chatbot's purpose or functionality.
7. `heroTitle`: Displays a welcome title when users interact with the chatbot.
8. `heroDescription`: Provide additional introductory text or information about the chatbot's capabilities.

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

For more information about React, refer to this [link here](https://react.dev/learn)

