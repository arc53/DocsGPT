# DocsGPT react widget


This widget will allow you to embed a DocsGPT assistant in your React app or any HTML based file.

## Usage

To embed the widget into an HTML file, do the following:

1. create a root element where widget would live and/or get rendered. It's important the element is given the specified id:
```<div id="docsgpt-widget-container"></div>```

While default props have been provided to the core DocsGPTWidget that gets rendered into the above ```div```, you can still specify the following dataset attributes where applicable:
- data-apiHost
- data-selectDocs 
- data-apiKey
- data-avatar 
- data-title
- data-description 
- data-heroTitle 
- data-heroDescription


2. Add below script tag to fetch hosted script. Tag can come just before your closing ```</body>``` tag:
```<script src="https://docsgpt-widget.vercel.app/index.96e2502d.js"></script>```


## Our github

[DocsGPT](https://github.com/arc53/DocsGPT)

You can find the source code in the extensions/react-widget folder.

