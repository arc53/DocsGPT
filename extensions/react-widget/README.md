# DocsGPT react widget


This widget will allow you to embed a DocsGPT assistant in your React app.

## Installation

```bash
npm install  docsgpt
```

## Usage

### React

```javascript
    import { DocsGPTWidget } from "docsgpt";

    const App = () => {
      return <DocsGPTWidget />;
    };
```

To link the widget to your api and your documents you can pass parameters to the <DocsGPTWidget /> component.

```javascript
    import { DocsGPTWidget } from "docsgpt";

    const App = () => {
      return <DocsGPTWidget
             apiHost = 'http://localhost:7001',
             selectDocs = 'default',
             apiKey = '',
             avatar = 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
             title = 'Get AI assistance',
             description = 'DocsGPT\'s AI Chatbot is here to help',
             heroTitle = 'Welcome to DocsGPT !',
             heroDescription='This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.'
             />;
    };
```

### Html

```html
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <title></title>
      </head>
      <body>
        <div id="widget-container"></div>
        <!-- Include the widget script -->
        <script src="path/to/your/dist/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('widget-container');
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
        <title></title>
      </head>
      <body>
        <div id="widget-container"></div>
        <!-- Include the widget script -->
        <script src="path/to/your/dist/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('widget-container', , {
              apiHost: 'http://localhost:7001',
              selectDocs: 'default',
              apiKey: '',
              avatar: 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
              title: 'Get AI assistance',
              description: "DocsGPT's AI Chatbot is here to help",
              heroTitle: 'Welcome to DocsGPT !',
              heroDescription: 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.'
            });
          }
        </script>
      </body>
    </html>
```


## Our github

[DocsGPT](https://github.com/arc53/DocsGPT)

You can find the source code in the extensions/react-widget folder.

