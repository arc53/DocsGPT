import { Doc } from '../models/misc';

export async function getDocs(): Promise<Array<Doc>> {
  //Fetch default source docs
  const response = await fetch(
    'https://d3dg1063dc54p9.cloudfront.net/combined.json',
  );
  const data = await response.json();

  //Create array of Doc objects
  const docs: Array<Doc> = [];

  data.forEach((doc: Doc) => {
    docs.push(doc);
  });

  return docs;
}
