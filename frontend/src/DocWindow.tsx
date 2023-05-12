import React, { useEffect, useState } from 'react';

export default function DocWindow(props: { sources: string[] }) {
  if (props.sources === undefined) {
    return <div>Here is the section to show the document the answer from.</div>;
  } else {
    return <div> Good News. Conversation give you the file name.</div>;
  }

  const [html, setHtml] = useState('');
  useEffect(() => {
    console.log(props.sources);

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
  }, [props.sources]);

  return (
    <div dangerouslySetInnerHTML={{ __html: html }} />
    // <div>Hello This is docWindows.</div>
  );
}
