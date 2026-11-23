// The REST API's endpoint pages (/API/endpoints/...), generated at build time
// from the Swagger snapshot in data/swagger.json. Nothing is written to content/:
// the "Generated docs" workflow refreshes the snapshot after each merge, and the
// pages follow it on the next build. Server-only: components/api-page.jsx
// imports it only inside its `typeof window === 'undefined'` branch, which the
// browser bundle drops.
import { upgrade } from '@scalar/openapi-upgrader';
import { createOpenAPI } from 'fumadocs-openapi/server';

import spec from '../data/swagger.json';
import { groupTitle, sentence } from './api-groups';

export const OPENAPI_ID = 'docsgpt';

/**
 * The token note the REST API reference shows for an operation, as Markdown.
 *
 * @param {Record<string, any>} operation A Swagger operation object.
 * @returns {string} The note.
 */
function tokenNote(operation) {
  // `security: []`: the token in the path is the credential, as on an approval or trigger link.
  if (Array.isArray(operation.security) && operation.security.length === 0) {
    return 'Public: the token in the path authorizes the request, so it needs no sign-in or other credential.';
  }
  if (operation['x-pat-denied']) {
    return 'Not available to [personal access tokens](/API/personal-access-tokens); call it from a signed-in session.';
  }
  const scopes = operation['x-pat-scopes'] || [];
  if (scopes.length === 0) return 'Any valid [personal access token](/API/personal-access-tokens) can call it.';
  return `[Personal access token](/API/personal-access-tokens) scope: ${scopes.map((s) => `\`${s}\``).join(' or ')}.`;
}

/**
 * A short title for an operation that has no summary: the first sentence of
 * its description, or its method and path when that is long or missing.
 *
 * @param {string} method The HTTP method.
 * @param {string} path The route.
 * @param {Record<string, any>} operation A Swagger operation object.
 * @returns {string} The title.
 */
function operationTitle(method, path, operation) {
  // Titles are plain text (page titles, the sidebar), so code markup is dropped.
  const text = (operation.description || '').replace(/`/g, '');
  // A sentence ends at . ! or ? and a space, but not inside "e.g." or "i.e.".
  const first = text.split(/(?<!\We\.g\.|\Wi\.e\.)(?<=[.!?])\s/)[0].trim().replace(/[.!?]$/, '');
  if (first && first.length <= 70 && !first.includes('\n')) return first;
  return `${method.toUpperCase()} ${path}`;
}

/**
 * Description text made safe for the endpoint pages' Markdown renderer, which
 * drops anything that looks like HTML: a `<placeholder>` outside a code span
 * becomes `&lt;placeholder>`, so it shows as written. The double backticks of
 * the docstrings' reStructuredText become Markdown code spans.
 *
 * @param {string} text A description from the Swagger document.
 * @returns {string} The Markdown to render.
 */
export function markdownText(text) {
  return text
    .replace(/``/g, '`')
    .split(/(`[^`]*`)/)
    .map((part, index) => (index % 2 ? part : part.replace(/</g, '&lt;')))
    .join('');
}

/**
 * Applies markdownText() to every description in a document, in place. Summaries
 * are titles, shown as plain text, so they stay as they are.
 *
 * @param {unknown} value A Swagger document or part of one.
 */
function cleanDescriptions(value) {
  if (Array.isArray(value)) {
    value.forEach(cleanDescriptions);
  } else if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (key === 'description' && typeof child === 'string') value[key] = markdownText(child);
      else cleanDescriptions(child);
    }
  }
}

/**
 * The snapshot, prepared for the endpoint pages and upgraded from Swagger 2.0
 * to OpenAPI 3.1 (fumadocs-openapi may upgrade it further when it loads it).
 *
 * flask-restx registers one tag per namespace, so a tag shared by several
 * namespaces appears more than once; each tag is kept once, with its display
 * name. Every operation gets a title (`summary`), an operationId no other
 * operation shares (it names the page) and its personal access token note;
 * descriptions are made safe for Markdown (markdownText). The document declares
 * the bearer credential and a server URL the playground uses; readers point it
 * at their own instance.
 *
 * @returns {Record<string, any>} An OpenAPI 3.1 document.
 */
export function endpointDocument() {
  const swagger = structuredClone(spec);
  const seen = new Set();
  swagger.tags = (swagger.tags || [])
    .filter((tag) => !seen.has(tag.name) && seen.add(tag.name))
    .map((tag) => ({ ...tag, 'x-displayName': groupTitle(tag.name) }));
  const operations = Object.entries(swagger.paths).flatMap(([path, item]) =>
    Object.entries(item)
      .filter(([, operation]) => operation && typeof operation === 'object' && operation.responses)
      .map(([method, operation]) => ({ path, method, operation })),
  );
  const idCounts = new Map();
  for (const { operation } of operations) idCounts.set(operation.operationId, (idCounts.get(operation.operationId) ?? 0) + 1);
  for (const { path, method, operation } of operations) {
    if (!operation.operationId || idCounts.get(operation.operationId) > 1) {
      operation.operationId = `${method}_${path.replace(/^\/api\//, '').replace(/[^a-zA-Z0-9]+/g, '_')}`;
    }
    operation.summary ||= operationTitle(method, path, operation);
    const text = [operation.description && sentence(operation.description), tokenNote(operation)];
    operation.description = text.filter(Boolean).join('\n\n');
  }
  cleanDescriptions(swagger.paths);
  cleanDescriptions(swagger.definitions);
  const doc = upgrade(swagger, '3.1');
  doc.servers = [
    {
      url: '{instance}',
      description: 'Your DocsGPT API',
      variables: { instance: { default: 'http://localhost:7091' } },
    },
  ];
  doc.components = {
    ...doc.components,
    securitySchemes: {
      bearer: {
        type: 'http',
        scheme: 'bearer',
        description:
          'A session token or a personal access token. Leave it empty when the instance runs without ' +
          'authentication (`AUTH_TYPE` unset).',
      },
    },
  };
  doc.security = [{ bearer: [] }];
  return doc;
}

export const openapi = createOpenAPI({
  input: { [OPENAPI_ID]: async () => endpointDocument() },
  // Each page would otherwise carry the whole document in its HTML; the
  // browser loads it once from /api/openapi/<id> instead.
  includeDocument: false,
});
