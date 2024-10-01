const API_ENDPOINT = "http://localhost:7091/api/answer"; // Replace with your API endpoint

const widgetInitMessage = document.getElementById("docsgpt-init-message");
const widgetAnswerMessage = document.getElementById("docsgpt-answer");
const widgetAnswerMessageP = widgetAnswerMessage.querySelector("p");
const askDocsGPTButton = document.getElementById("ask-docsgpt");
const chatInput = document.getElementById("docsgpt-chat-input");
const chatForm = document.getElementById("docsgpt-chat-form");
const chatProcessing = document.getElementById("docsgpt-chat-processing");

async function sendMessage(message) {
  const requestData = {
    "question": message,
    "active_docs": "default",
    "api_key": "token",
    "embeddings_key": "token",
    "model": "default",
    "history": null,
  }
  const response = await fetch(API_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestData),
  });
  const data = await response.json();
  return data.answer;
}

askDocsGPTButton.addEventListener("click", () => {
  askDocsGPTButton.classList.add("hidden");
  chatForm.classList.remove("hidden");
  chatForm.focus();
  widgetInitMessage.classList.remove("hidden");
  widgetAnswerMessage.classList.add("hidden");


});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  chatInput.value = "";
  chatForm.classList.add("hidden");
  chatProcessing.classList.remove("hidden");

const reply = await sendMessage(message);
chatProcessing.classList.add("hidden");

// inside <p> tag
widgetAnswerMessageP.innerHTML = reply;
widgetAnswerMessage.classList.remove("hidden");
widgetInitMessage.classList.add("hidden");
askDocsGPTButton.classList.remove("hidden");
});