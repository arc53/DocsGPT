(async function () {
  // Fetch the HTML, CSS, and JavaScript from your server or CDN
  const [htmlRes, jsRes] = await Promise.all([
    fetch("https://s3-eu-west-2.amazonaws.com/arc53data/widget.html"),
    // fetch("https://s3-eu-west-2.amazonaws.com/arc53data/tailwind.css"),
    fetch("https://s3-eu-west-2.amazonaws.com/arc53data/script.js"),
  ]);

  const html = await htmlRes.text();
  //const css = await cssRes.text();
  const js = await jsRes.text();

  // create a new link element
  const link = document.createElement("link");

  //set the rel, href, type, and integrity attributes
  link.rel = "stylesheet";
  link.href = "https://cdn.tailwindcss.com/";
  link.type = "text/css";
  link.integrity = "sha384-PDOmVviaTm8N1W35y1NSmo80w6GPaGhbDuOBAF/5hRffaeGc6yOwIo1qAt4gqLGA%";

  // get the document head and append the link element to it
  // document.head.appendChild(link);



  // Create a style element for the CSS
  // const style = document.createElement("style");
  // style.innerHTML = css;
  // document.head.appendChild(style);

  // Create a container for the chat widget and inject the HTML
  const chatWidgetContainer = document.createElement("div");
  chatWidgetContainer.innerHTML = html;
  document.body.appendChild(chatWidgetContainer);

  // Execute the JavaScript code
  const script = document.createElement("script");
  script.innerHTML = js;
  document.body.appendChild(script);
})();
