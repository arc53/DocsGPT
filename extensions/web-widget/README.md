# Chat Widget

A simple chat widget that can be easily integrated into any website.

## Installation

1. Host the `widget.html`, `styles.css`, and `script.js` files from the `src` folder on your own server or a Content Delivery Network (CDN). Make sure to note the URLs for these files.

2. Update the URLs in the `dist/chat-widget.js` file to match the locations of your hosted files:

   ```javascript
   fetch("https://your-server-or-cdn.com/path/to/widget.html"),
   fetch("https://your-server-or-cdn.com/path/to/styles.css"),
   fetch("https://your-server-or-cdn.com/path/to/script.js"),
    ```
   
3. Host the `dist/chat-widget.js` file on your own server or a Content Delivery Network (CDN). Make sure to note the URL for this file.


##Integration

To integrate the chat widget into a website, add the following script tag to the HTML file, replacing URL_TO_CHAT_WIDGET_JS with the actual URL of your hosted chat-widget.js file:
```javascript
<script src="URL_TO_CHAT_WIDGET_JS"></script>
```