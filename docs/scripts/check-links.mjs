#!/usr/bin/env node
// Checks the internal links of the built docs site, offline.
//
// Run it after `npm run build`. It reads every prerendered page under
// .next/server/app and checks that each same-site link (<a href>, and the src
// or poster of images and videos) points at a built page or a file in public/,
// and that a #fragment names an id on the target page. External links are not
// fetched; the weekly job in .github/workflows/docs.yml covers those.
//
// A link to a path that next.config.js redirects is reported too: it works, but
// the page should link the destination directly.
//
//   node scripts/check-links.mjs [built-app-dir]

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const APP_DIR = process.argv[2] ?? join(DOCS_ROOT, '.next', 'server', 'app');
const PUBLIC_DIR = join(DOCS_ROOT, 'public');
const SITE_ORIGIN = 'https://docs.docsgpt.cloud';
// Next.js internals and build output that is not a page.
const IGNORED_PREFIXES = ['/_next/', '/_pagefind/', '/_vercel/'];
const INTERNAL_PAGES = new Set(['/_not-found', '/_global-error']);

/**
 * Lists every file below a folder.
 *
 * @param {string} dir Absolute folder path.
 * @returns {string[]} Absolute file paths.
 */
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

/**
 * Decodes the HTML entities that appear in attribute values.
 *
 * @param {string} value Raw attribute value.
 * @returns {string} Decoded value.
 */
function decodeEntities(value) {
  return value
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

/**
 * Percent-decodes a URL part, leaving it as is when it is malformed.
 *
 * @param {string} value URL path or fragment.
 * @returns {string} Decoded value.
 */
function safeDecode(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Reads the redirect sources from next.config.js without loading Next.js.
 *
 * @returns {Set<string>} Redirected paths.
 */
function redirectSources() {
  const file = join(DOCS_ROOT, 'next.config.js');
  if (!existsSync(file)) return new Set();
  const text = readFileSync(file, 'utf8');
  return new Set([...text.matchAll(/source:\s*['"]([^'"]+)['"]/g)].map((m) => m[1].replace(/\/$/, '') || '/'));
}

/**
 * Extracts the checkable links from one page's HTML.
 *
 * @param {string} html The page's HTML.
 * @returns {string[]} Link targets as written in the page.
 */
function extractLinks(html) {
  const links = [];
  for (const m of html.matchAll(/<a\b[^>]*?\shref="([^"]*)"/gi)) links.push(m[1]);
  for (const m of html.matchAll(/<(?:img|video|source)\b[^>]*?\s(?:src|poster)="([^"]*)"/gi)) links.push(m[1]);
  return links.map(decodeEntities);
}

/**
 * Collects the ids a page defines, which #fragments may point at.
 *
 * @param {string} html The page's HTML.
 * @returns {Set<string>} Element ids and anchor names.
 */
function extractIds(html) {
  const ids = new Set();
  for (const m of html.matchAll(/\s(?:id|name)="([^"]*)"/g)) ids.add(decodeEntities(m[1]));
  return ids;
}

function main() {
  if (!existsSync(APP_DIR)) {
    console.error(`No build output at ${APP_DIR}. Run \`npm run build\` first.`);
    process.exit(2);
  }

  const pages = new Map();
  for (const file of walk(APP_DIR).filter((f) => f.endsWith('.html'))) {
    const route = '/' + relative(APP_DIR, file).split(/[\\/]/).join('/').replace(/\.html$/, '');
    const normalized = route === '/index' ? '/' : route;
    if (INTERNAL_PAGES.has(normalized)) continue;
    const html = readFileSync(file, 'utf8');
    pages.set(normalized, { html, ids: extractIds(html) });
  }
  const redirects = redirectSources();

  const problems = new Map();
  const report = (page, link, reason) => {
    const key = `${link}  (${reason})`;
    if (!problems.has(key)) problems.set(key, new Set());
    problems.get(key).add(page);
  };

  let checked = 0;
  for (const [route, { html }] of pages) {
    for (const raw of extractLinks(html)) {
      if (!raw || /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(raw)) {
        if (!raw.startsWith(SITE_ORIGIN)) continue;
      }
      const base = new URL(route === '/' ? '/' : route, SITE_ORIGIN);
      const url = new URL(raw, base);
      if (url.origin !== SITE_ORIGIN) continue;
      const path = safeDecode(url.pathname).replace(/\/$/, '') || '/';
      if (IGNORED_PREFIXES.some((prefix) => path.startsWith(prefix.replace(/\/$/, '')))) continue;
      checked += 1;

      const target = pages.get(path);
      if (!target) {
        if (existsSync(join(PUBLIC_DIR, path)) && statSync(join(PUBLIC_DIR, path)).isFile()) continue;
        report(route, raw, redirects.has(path) ? 'redirected: link the destination' : 'no such page or file');
        continue;
      }
      const fragment = safeDecode(url.hash.replace(/^#/, ''));
      if (fragment && !target.ids.has(fragment)) report(route, raw, `no #${fragment} on ${path}`);
    }
  }

  if (problems.size) {
    console.error(`Found ${problems.size} broken internal link(s):\n`);
    for (const [key, sources] of [...problems].sort()) {
      console.error(`  ${key}\n    on ${[...sources].sort().join(', ')}`);
    }
    process.exit(1);
  }
  console.log(`Checked ${checked} internal links on ${pages.size} pages; all resolve.`);
}

main();
