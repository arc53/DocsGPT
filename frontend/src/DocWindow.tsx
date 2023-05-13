import React, { useEffect, useState } from 'react';
import { globalSetFilepath } from './helper/getDocsHelper';

export default function DocWindow() {
  if (globalSetFilepath === 'a') {
    return <div>File not found</div>;
  }

  const [filepath, setFilepath] = useState(globalSetFilepath);
  const [html, setHtml] = useState('');

  useEffect(() => {
    const intervalId = setInterval(() => {
      if (globalSetFilepath !== filepath) {
        setFilepath(globalSetFilepath);
      }
    }, 500);
    return () => clearInterval(intervalId);
  }, [filepath]);

  const data = {
    user: 'local',
    path: filepath,
  };
  // console.log("GLOBAL" + globalSetFilepath);

  useEffect(() => {
    async function getHtml() {
      fetch('http://localhost:5001/api/get_docs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
        mode: 'cors',
      })
        .then((response) => response.text())
        .then((data) => setHtml(data))
        .catch((error) => console.error(error));
    }
    getHtml();
  }, [filepath]);

  return (
    <div dangerouslySetInnerHTML={{ __html: html }} />
    // <div>Hello This is docWindows.</div>
  );
}
