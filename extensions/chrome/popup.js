document.getElementById("message-form").addEventListener("submit", function(event) {
    event.preventDefault();
    var message = document.getElementById("message-input").value;
    chrome.runtime.sendMessage({msg: "sendMessage", message: message}, function(response) {
      console.log(response.response);
      msg_html = '<div class="bg-blue-500 text-white p-2 rounded-lg mb-2 self-end"><p class="text-sm">'
      msg_html += message
      msg_html += '</p></div>'
      document.getElementById("messages").innerHTML += msg_html;
      let chatWindow = document.getElementById("chat-container");
      chatWindow.scrollTop = chatWindow.scrollHeight;

    });

    document.getElementById("message-input").value = "";
    var conversation_state = localStorage.getItem("conversation_state");
    // check if conversation state is null
    if (conversation_state == null) {
      conversation_state = 0;
      localStorage.setItem("conversation_state", conversation_state);
    }

    // send post request to server http://127.0.0.1:5000/ with message in json body
    fetch('http://127.0.0.1:5001/api/answer', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({question: message, history: null}),
    })
    .then(response => response.json())
    .then(data => {
      console.log('Success:', data);

        
        msg_html = '<div class="bg-indigo-500 text-white p-2 rounded-lg mb-2 self-start"><code class="text-sm">'
        msg_html += data.answer
        msg_html += '</code></div>'
        document.getElementById("messages").innerHTML += msg_html;
        let chatWindow = document.getElementById("chat-container");
        chatWindow.scrollTop = chatWindow.scrollHeight;
    })


  });
  