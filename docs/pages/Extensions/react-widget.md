### Setting up the DocsGPT Widget in Your React Project

### Introduction:
The DocsGPT Widget is a powerful tool that allows you to integrate AI-powered documentation assistance into your web applications. This guide will walk you through the installation and usage of the DocsGPT Widget in your React project. Whether you're building a web app or a knowledge base, this widget can enhance your user experience.

### Installation
First, make sure you have Node.js and npm installed in your project. Then go to your project and install a new dependency: `npm install docsgpt`.

### Usage
In the file where you want to use the widget, import it and include the CSS file:
```js
import { DocsGPTWidget } from "docsgpt";
import "docsgpt/dist/style.css";
```


Now, you can use the widget in your component like this :
```jsx
<DocsGPTWidget
  apiHost="https://your-docsgpt-api.com"
  selectDocs="local/docs.zip"
  apiKey=""
/>
```
DocsGPTWidget takes 3 **props**:
1. `apiHost` — The URL of your DocsGPT API.
2. `selectDocs` — The documentation source that you want to use for your widget (e.g. `default` or `local/docs1.zip`).
3. `apiKey` — Usually, it's empty.

### How to use DocsGPTWidget with [Nextra](https://nextra.site/) (Next.js + MDX)
Install your widget as described above and then go to your `pages/` folder and create a new file `_app.js` with the following content:
```js
import { DocsGPTWidget } from "docsgpt";
import "docsgpt/dist/style.css";

export default function MyApp({ Component, pageProps }) {
    return (
        <>
            <Component {...pageProps} />
            <DocsGPTWidget selectDocs="local/docsgpt-sep.zip/"/>
        </>
    )
}
```  


