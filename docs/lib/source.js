// The docs content: every page under content/, plus the REST API endpoint
// pages generated from data/swagger.json (lib/openapi.js). The sidebar comes
// from content/**/meta.js (folder title and page order) and each page's
// frontmatter (`sidebarTitle`, else `title`).
import { remarkMdxMermaid } from 'fumadocs-core/mdx-plugins';
import { loader } from 'fumadocs-core/source';
import { metaSchema, pageSchema } from 'fumadocs-core/source/schema';
import { applyMdxPreset } from 'fumadocs-mdx/config';
import { defineDocs } from 'fumadocs-mdx/macro';
import { z } from 'zod';

import { openapi } from './openapi';

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * A URL segment for a generated endpoint page: lower case, words joined by hyphens.
 *
 * @param {string} name A tag name or operation id, such as `agents_folders`.
 * @returns {string} The segment, such as `agents-folders`.
 */
function urlSegment(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

const docs = defineDocs({
  dir: 'content',
  docs: {
    schema: pageSchema.extend({
      // The sidebar label, when it differs from the page title (the emoji labels).
      sidebarTitle: z.string().optional(),
      // YYYY-MM-DD, see docs/AGENTS.md. YAML may hand it over as a Date.
      lastUpdated: z
        .union([z.string(), z.date()])
        .transform((value) => (value instanceof Date ? value.toISOString().slice(0, 10) : value))
        .pipe(z.string().regex(DATE_RE))
        .optional(),
    }),
    mdxOptions: applyMdxPreset({
      remarkPlugins: (plugins) => [...plugins, remarkMdxMermaid],
    }),
    postprocess: {
      includeProcessedMarkdown: true,
    },
  },
  meta: {
    schema: metaSchema,
  },
});

/**
 * Shows a page's `sidebarTitle` in the sidebar instead of its `title`.
 *
 * @returns {import('fumadocs-core/source').LoaderPlugin} The loader plugin.
 */
function sidebarTitles() {
  return {
    name: 'docsgpt:sidebar-titles',
    transformPageTree: {
      file(node, filePath) {
        if (!filePath) return node;
        const file = this.storage.read(filePath);
        const label = file?.format === 'page' ? file.data.sidebarTitle : undefined;
        return label ? { ...node, name: label } : node;
      },
    },
  };
}

export const source = loader(
  {
    docs: docs.toFumadocsSource(),
    // One page per operation, in a folder per tag: /API/endpoints/<tag>/<operation>.
    openapi: await openapi.staticSource({
      baseDir: 'API/endpoints',
      per: 'operation',
      groupBy: 'tag',
      slugify: urlSegment,
      name(output) {
        const { path, method } = output.item;
        const operation = this.document.paths?.[path]?.[method];
        return urlSegment(operation?.operationId ?? `${method}-${path}`);
      },
    }),
  },
  {
    baseUrl: '/',
    plugins: [sidebarTitles(), openapi.loaderPlugin()],
  },
);

export const ENDPOINTS_URL = '/API/endpoints';

/**
 * The sidebar for every page but the REST endpoint pages: the endpoint folder
 * becomes one link to its overview. Its 265 pages stay in the endpoint pages'
 * own sidebar (app/API/endpoints/layout.jsx), so the other pages don't carry
 * them in their HTML.
 *
 * @returns {import('fumadocs-core/page-tree').Root} The page tree.
 */
export function docsTree() {
  const trim = (nodes) =>
    nodes.map((node) => {
      if (node.type !== 'folder') return node;
      if (node.index?.url === ENDPOINTS_URL) return { ...node.index, name: node.name, icon: node.icon };
      return { ...node, children: trim(node.children) };
    });
  const tree = source.getPageTree();
  return { ...tree, children: trim(tree.children) };
}
