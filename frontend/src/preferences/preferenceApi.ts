// not all properties in Doc are going to be present. Make some optional
export type Doc = {
  name: string;
  language: string;
  version: string;
  description: string;
  fullName: string;
  dat: string;
  docLink: string;
  model: string;
};

//Fetches all JSON objects from the source. We only use the objects with the "model" property in SelectDocsModal.tsx. Hopefully can clean up the source file later.
export async function getDocs(): Promise<Doc[] | null> {
  try {
    const response = await fetch(
      'https://d3dg1063dc54p9.cloudfront.net/combined.json',
    );
    const data = await response.json();

    const docs: Doc[] = [];

    data.forEach((doc: object) => {
      docs.push(doc as Doc);
    });

    return docs;
  } catch (error) {
    console.log(error);
    return null;
  }
}

export function getLocalApiKey(): string | null {
  const key = localStorage.getItem('DocsGPTApiKey');
  return key;
}

export function getLocalRecentDocs(): string | null {
  const doc = localStorage.getItem('DocsGPTRecentDocs');
  return doc;
}

export function setLocalApiKey(key: string): void {
  localStorage.setItem('DocsGPTApiKey', key);
}

export function setLocalRecentDocs(doc: Doc): void {
  localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(doc));
  let namePath = doc.name;
  if (doc.language === namePath) {
    namePath = '.project';
  }

  const docPath =
    doc.name === 'default'
      ? 'default'
      : doc.language +
        '/' +
        namePath +
        '/' +
        doc.version +
        '/' +
        doc.model +
        '/';
  const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
  fetch(apiHost + '/api/docs_check', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      docs: docPath,
    }),
  }).then((response) => response.json());
}
