// The REST API's endpoint pages (/API/endpoints/...), generated at build time
// from the Swagger snapshot in data/swagger.json. Nothing is written to content/:
// the "Generated docs" workflow refreshes the snapshot after each merge, and the
// pages follow it on the next build. Server-only: never import this from a
// client component.
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
  const first = (operation.description || '').split(/(?<=[.!?])\s/)[0].trim().replace(/[.!?]$/, '');
  if (first && first.length <= 70 && !first.includes('\n')) return first;
  return `${method.toUpperCase()} ${path}`;
}

/**
 * The snapshot, prepared for the endpoint pages, as OpenAPI 3.1.
 *
 * flask-restx registers one tag per namespace, so a tag shared by several
 * namespaces appears more than once; each tag is kept once, with its display
 * name. Every operation gets a title (`summary`) and its description gains its
 * personal access token note.
 * The document declares the bearer credential and a server URL the playground
 * uses; readers point it at their own instance.
 *
 * @returns {Record<string, any>} An OpenAPI 3.1 document.
 */
export function endpointDocument() {
  const swagger = structuredClone(spec);
  const seen = new Set();
  swagger.tags = (swagger.tags || [])
    .filter((tag) => !seen.has(tag.name) && seen.add(tag.name))
    .map((tag) => ({ ...tag, 'x-displayName': groupTitle(tag.name) }));
  for (const [path, item] of Object.entries(swagger.paths)) {
    for (const [method, operation] of Object.entries(item)) {
      if (!operation || typeof operation !== 'object' || !operation.responses) continue;
      operation.summary ||= operationTitle(method, path, operation);
      const text = [operation.description && sentence(operation.description), tokenNote(operation)];
      operation.description = text.filter(Boolean).join('\n\n');
    }
  }
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
