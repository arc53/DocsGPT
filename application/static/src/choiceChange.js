  document.getElementById("select-docs").addEventListener("change", function() {
    localStorage.setItem('activeDocs', this.value)
  });