// This is the service worker script, which executes in its own context
// when the extension is installed or refreshed (or when you access its console).
// It would correspond to the background script in chrome extensions v2.

console.log("This prints to the console of the service worker (background script)");
chrome.runtime.onMessage.addListener(
    function(request, sender, sendResponse) {
        if (request.msg === "sendMessage") {
        sendResponse({response: "Message received"});
        }
    }
);