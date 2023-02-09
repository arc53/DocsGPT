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

