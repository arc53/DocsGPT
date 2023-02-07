
function docsIndex() {
    // loads latest index from https://raw.githubusercontent.com/arc53/DocsHUB/main/combined.json
    // and stores it in localStorage
    fetch('https://raw.githubusercontent.com/arc53/DocsHUB/main/combined.json')
        .then(response => response.json())
        .then(data => {
            console.log('Success:', data);
            localStorage.setItem("docsIndex", JSON.stringify(data));
        }
    )

}

document.getElementById("select-docs").addEventListener("change", function() {
localStorage.setItem('activeDocs', this.value)
     fetch('/api/docs_check', {
         method: 'POST',
         headers: {
             'Content-Type': 'application/json',
         },
         body: JSON.stringify({docs: this.value}),
     }).then(response => response.json()).then(
            data => {
                console.log('Success:', data);
            }
     )
});

