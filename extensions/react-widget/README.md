# DocsGPT react widget


This widget will allow you to embed a DocsGPT assistant in your React app.

## Installation

```bash
npm install  docsgpt
```

## Usage

```javascript
    import { DocsGPTWidget } from "docsgpt";
    import "docsgpt/dist/style.css";

    const App = () => {
      return <DocsGPTWidget />;
    };
```

To link the widget to your api and your documents you can pass parameters to the <DocsGPTWidget /> component.

```javascript
    import { DocsGPTWidget } from "docsgpt";
    import "docsgpt/dist/style.css";

    const App = () => {
      return <DocsGPTWidget apiHost="http://localhost:7001" selectDocs='default' apiKey=''/>;
    };
```


## Our github

[DocsGPT](https://github.com/arc53/DocsGPT)

You can find the source code in the extensions/react-widget folder.

