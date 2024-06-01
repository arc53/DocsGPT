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
        <meta charset="UTF-8" />
        <meta http-equiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>DocsGPT Widget</title>
      </head>
      <body>
        <div id="app"></div>
        <!-- Include the widget script -->
        <script src="./node_modules/docsgpt/dist/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('app');
          }
        </script>
      </body>
    </html>
```

##### Serve the HTML using Parcel: `parcel my-widget.html -p 3000`

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
        <!-- Include the widget script -->
        <script src="./node_modules/docsgpt/dist/main.js" type="module"></script>
        <script type="module">
          window.onload = function() {
            renderDocsGPTWidget('app', , {
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
