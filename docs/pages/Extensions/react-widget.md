### How to set up react docsGPT widget on your website:

### Installation
Go to your project and install a new dependency: `npm install docsgpt`.

### Usage
Go to your project and in the file where you want to use the widget, import it: 
```js
import { DocsGPTWidget } from "docsgpt";
import "docsgpt/dist/style.css";
```


Then you can use it like this: `<DocsGPTWidget />`

DocsGPTWidget takes 3 props:
1. `apiHost` — URL of your DocsGPT API.
2. `selectDocs` — documentation that you want to use for your widget (e.g. `default` or `local/docs1.zip`).
3. `apiKey` — usually it's empty.

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


