'use client';

import { createOpenAPIPage } from 'fumadocs-openapi/ui';
import { preload } from 'react-dom';

// Renders the REST API endpoint pages (/API/endpoints/...). The OpenAPI
// document is left out of each page's HTML and loaded once per browser
// session from /api/openapi/<id> (app/api/openapi/[id]/route.js).
export const OpenAPIPage = createOpenAPIPage({
  async loadDocument(id) {
    if (typeof window === 'undefined') {
      preload(`/api/openapi/${id}`, { as: 'fetch', crossOrigin: 'anonymous' });
      const { openapi } = await import('../lib/openapi');
      return (await openapi.getSchema(id)).bundled;
    }
    const response = await fetch(`/api/openapi/${id}`);
    if (!response.ok) throw new Error(`Could not load the API document (${response.status}).`);
    return response.json();
  },
});
