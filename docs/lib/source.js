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
    openapi: await openapi.staticSource({
      baseDir: 'API/endpoints',
      per: 'tag',
    }),
  },
  {
    baseUrl: '/',
    plugins: [sidebarTitles(), openapi.loaderPlugin()],
  },
);
