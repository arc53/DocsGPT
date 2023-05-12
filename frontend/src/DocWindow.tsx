import React, { useEffect, useState } from 'react';

export default function DocWindow() {
  const [html, setHtml] = useState('');

  useEffect(() => {
    async function getHtml() {
      fetch('http://localhost:5001/api/getdoctest', {
        method: 'GET',
        mode: 'cors',
      })
        .then((response) => response.text())
        .then((data) => setHtml(data))
        .catch((error) => console.error(error));
    }
    getHtml();
  }, []);

  return (
    <div dangerouslySetInnerHTML={{ __html: html }} />
    // <div>Hello This is docWindows.</div>
  );
}
