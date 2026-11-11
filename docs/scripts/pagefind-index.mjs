#!/usr/bin/env node
// Builds the Pagefind search index from the prerendered pages after `next build`.
//
// Next writes those pages to .next/server/app, except when a deployment adapter
// is active (Vercel turns one on): from Next 16.4 they go to
// .next/server/route-cache/APP_PAGE/<hash>/$/ instead, one folder per route
// group, laid out like .next/server/app. This indexes whichever layout the build
// produced, so search works in both.
//
//   node scripts/pagefind-index.mjs

import { existsSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as pagefind from 'pagefind';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SERVER_DIR = join(DOCS_ROOT, '.next', 'server');
const APP_DIR = join(SERVER_DIR, 'app');
const ROUTE_CACHE_DIR = join(SERVER_DIR, 'route-cache', 'APP_PAGE');
const OUTPUT_DIR = join(DOCS_ROOT, 'public', '_pagefind');

/**
 * Reports whether a folder holds any .html file, at any depth.
 *
 * @param {string} dir Absolute folder path.
 * @returns {boolean} True when at least one .html file is found.
 */
function hasHtml(dir) {
  return readdirSync(dir).some((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return hasHtml(path);
    return name.endsWith('.html');
  });
}

/**
 * Finds the folders the prerendered pages were written to.
 *
 * @returns {string[]} Absolute folder paths, each laid out like the site's URLs.
 */
function siteRoots() {
  if (existsSync(APP_DIR) && hasHtml(APP_DIR)) return [APP_DIR];
  if (!existsSync(ROUTE_CACHE_DIR)) return [];
  return readdirSync(ROUTE_CACHE_DIR)
    .map((hash) => join(ROUTE_CACHE_DIR, hash, '$'))
    .filter((dir) => existsSync(dir) && hasHtml(dir));
}

const roots = siteRoots();
const { index, errors } = await pagefind.createIndex();
if (!index) throw new Error(`Pagefind could not start: ${errors.join('; ')}`);

let pages = 0;
for (const path of roots) {
  const result = await index.addDirectory({ path });
  if (result.errors.length) throw new Error(`Pagefind failed on ${path}: ${result.errors.join('; ')}`);
  pages += result.page_count;
}

if (pages === 0) {
  await pagefind.close();
  console.error(`No prerendered pages found under ${APP_DIR} or ${ROUTE_CACHE_DIR}.`);
  process.exit(1);
}

const written = await index.writeFiles({ outputPath: OUTPUT_DIR });
if (written.errors.length) throw new Error(`Pagefind could not write the index: ${written.errors.join('; ')}`);
await pagefind.close();
console.log(`Pagefind read ${pages} HTML files and wrote the index to public/_pagefind.`);
