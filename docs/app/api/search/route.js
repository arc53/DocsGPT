import { createFromSource } from 'fumadocs-core/search/server';

import { source } from '../../../lib/source';

// The search box queries this route; the index lives on the server, so readers
// download results, not the whole index (which the endpoint pages make large).
export const { GET } = createFromSource(source);
