// if you checked "fancy-settings" in extensionizr.com, uncomment this lines

// var settings = new Store("settings", {
//     "sample_setting": "This is how you use Store.js to remember values"
// });


//example of using a message handler from the inject scripts
chrome.extension.onMessage.addListener(
  function(request, sender, sendResponse) {
  	chrome.pageAction.show(sender.tab.id);
    sendResponse();
  });


  chrome.runtime.onMessage.addListener(
    function(request, sender, sendResponse) {
      if (request.msg === "sendMessage") {
        sendResponse({response: "Message received"});
      }
    });
  