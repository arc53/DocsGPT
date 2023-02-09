function resetApiKey() {
  const modal = document.getElementById("modal");
  modal.classList.toggle("hidden");
}

const apiKeyForm = document.getElementById("api-key-form");
if (apiKeyForm) {
  apiKeyForm.addEventListener("submit", function(event) {
    event.preventDefault();

    const apiKeyInput = document.getElementById("api-key-input");
    const apiKey = apiKeyInput.value;

    localStorage.setItem("apiKey", apiKey);

    apiKeyInput.value = "";
    modal.classList.toggle("hidden");
  });
}
