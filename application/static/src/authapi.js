function resetApiKey() {
  document.getElementById('modal').classList.toggle('hidden')
}


var el2 = document.getElementById('api-key-form');
if (el2) {
    el2.addEventListener("submit", function (event) {
        event.preventDefault()
        var apiKey = document.getElementById("api-key-input").value;
        document.getElementById('modal').classList.toggle('hidden')
        localStorage.setItem('apiKey', apiKey)
        document.getElementById('api-key-input').value = ''
    });
}
