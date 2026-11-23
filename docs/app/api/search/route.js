import { createFromSource } from 'fumadocs-core/search/server';

import { source } from '../../../lib/source';

// The search box's index, built from every page at build time and served as
// one static JSON file (the "static" client in app/layout.jsx queries it in the browser).
export const revalidate = false;
export const { staticGET: GET } = createFromSource(source);
