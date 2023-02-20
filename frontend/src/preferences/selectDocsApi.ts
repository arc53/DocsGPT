//Exporting Doc type from here since its the first place its used and seems needless to make an entire file for it.
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
    //Fetch default source docs
    const response = await fetch(
      'https://d3dg1063dc54p9.cloudfront.net/combined.json',
    );
    const data = await response.json();

    //Create array of Doc objects
    const docs: Doc[] = [];

    data.forEach((doc: Doc) => {
      docs.push(doc);
    });

    return docs;
  } catch (error) {
    return null;
  }
}
