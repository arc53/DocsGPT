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

export async function getLocalApiKey(): Promise<string | null> {
  try {
    const key = localStorage.getItem('DocsGPTApiKey');
    if (key) {
      return key;
    }
    return null;
  } catch (error) {
    console.log(error);
    return null;
  }
}

export async function getLocalRecentDocs(): Promise<Doc | null> {
  try {
    const doc = localStorage.getItem('DocsGPTRecentDocs');
    if (doc) {
      return JSON.parse(doc);
    }
    return null;
  } catch (error) {
    console.log(error);
    return null;
  }
}

export async function setLocalApiKey(key: string): Promise<void> {
  try {
    localStorage.setItem('DocsGPTApiKey', key);
  } catch (error) {
    console.log(error);
  }
}

export async function setLocalRecentDocs(doc: Doc): Promise<void> {
  try {
    localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(doc));
  } catch (error) {
    console.log(error);
  }
}
