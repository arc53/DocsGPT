#!/usr/bin/env node
// Builds public/llms.txt (https://llmstxt.org) from the docs sidebar.
//
// Sections and order come from the content/**/_meta.js files, the same files
// that drive the sidebar; each link's text is the sidebar title and its note is
// the page's frontmatter `description`. Entries with `display: "hidden"`,
// separators and external links are skipped. A page that exists but is missing
// from its folder's _meta.js is still listed, after the listed ones, because
// Nextra shows it in the sidebar too.
//
//   node scripts/generate-llms.mjs          write public/llms.txt
//   node scripts/generate-llms.mjs --check  exit 1 if public/llms.txt is stale
//   node scripts/generate-llms.mjs --print  print the result without writing it

import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONTENT_DIR = join(DOCS_ROOT, 'content');
const OUTPUT = join(DOCS_ROOT, 'public', 'llms.txt');
const SITE_URL = 'https://docs.docsgpt.cloud';
const PAGE_EXTENSIONS = ['.mdx', '.md'];

const HEADER = `# DocsGPT

> DocsGPT is an open-source platform for building AI agents and assistants with document retrieval, tools, and
> multi-model support. Run it with Docker, pip or Kubernetes, with hosted or local models.

This file maps the DocsGPT documentation for LLMs and coding agents. It is generated from the docs sidebar by
\`docs/scripts/generate-llms.mjs\`; don't edit it by hand.
`;

/**
 * Loads a folder's _meta.js as a plain object.
 *
 * The file is an ES module whose default export is an object literal. It is
 * imported from a data: URL so this works whatever module type package.json
 * declares.
 *
 * @param {string} dir Absolute folder path.
 * @returns {Promise<Record<string, unknown>>} The exported object, or {} when there is no _meta.js.
 */
async function loadMeta(dir) {
  const file = join(dir, '_meta.js');
  if (!existsSync(file)) return {};
  const source = readFileSync(file, 'utf8');
  const module = await import(`data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`);
  return module.default ?? {};
}

/**
 * Reads the frontmatter block at the top of a page.
 *
 * Handles the subset the docs use: `key: value` lines with optional single or
 * double quotes, plus `>` and `|` block scalars.
 *
 * @param {string} file Absolute page path.
 * @returns {Record<string, string>} Frontmatter keys and values.
 */
function readFrontmatter(file) {
  const text = readFileSync(file, 'utf8');
  const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) return {};
  const data = {};
  const lines = match[1].split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const kv = lines[i].match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!kv) continue;
    let value = kv[2].trim();
    if (value === '>' || value === '|' || value === '>-' || value === '|-') {
      const block = [];
      while (i + 1 < lines.length && (/^\s+\S/.test(lines[i + 1]) || lines[i + 1].trim() === '')) {
        i += 1;
        block.push(lines[i].trim());
      }
      value = block.join(' ');
    } else if (/^'.*'$/.test(value)) {
      value = value.slice(1, -1).replace(/''/g, "'");
    } else if (/^".*"$/.test(value)) {
      value = value.slice(1, -1).replace(/\\"/g, '"');
    }
    data[kv[1]] = value.replace(/\s+/g, ' ').trim();
  }
  return data;
}

/**
 * Removes emoji and the joiners that come with them from a sidebar title.
 *
 * @param {string} title A title that may start with an emoji.
 * @returns {string} The title as plain text.
 */
function plainTitle(title) {
  return title
    .replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}\u{20E3}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Normalizes a _meta.js entry to an object.
 *
 * @param {unknown} value A string title or an entry object.
 * @returns {Record<string, unknown>} The entry as an object.
 */
function entryOf(value) {
  if (typeof value === 'string') return { title: value };
  if (value && typeof value === 'object') return value;
  return {};
}

/**
 * Finds the page file for a key inside a folder.
 *
 * @param {string} dir Absolute folder path.
 * @param {string} key File name without extension.
 * @returns {string | null} Absolute page path, or null.
 */
function pageFile(dir, key) {
  for (const ext of PAGE_EXTENSIONS) {
    const file = join(dir, key + ext);
    if (existsSync(file)) return file;
  }
  return null;
}

/**
 * Turns a page path into its public URL.
 *
 * @param {string} file Absolute page path under content/.
 * @returns {string} The page's URL on the docs site.
 */
function pageUrl(file) {
  const route = relative(CONTENT_DIR, file)
    .split(/[\\/]/)
    .join('/')
    .replace(/\.(mdx|md)$/, '')
    .replace(/(^|\/)index$/, '');
  return route ? `${SITE_URL}/${route}` : `${SITE_URL}/`;
}

/**
 * Lists a folder's children in sidebar order: the _meta.js keys first, then
 * any page or folder it doesn't mention, sorted by name (index first).
 *
 * @param {string} dir Absolute folder path.
 * @param {Record<string, unknown>} meta The folder's _meta.js export.
 * @returns {string[]} Child keys in order.
 */
function orderedKeys(dir, meta) {
  const keys = Object.keys(meta);
  const unlisted = readdirSync(dir)
    .filter((name) => !name.startsWith('_') && !name.startsWith('.'))
    .map((name) => {
      if (statSync(join(dir, name)).isDirectory()) return name;
      const ext = PAGE_EXTENSIONS.find((e) => name.endsWith(e));
      return ext ? name.slice(0, -ext.length) : null;
    })
    .filter((key) => key && !keys.includes(key))
    .sort((a, b) => (a === 'index' ? -1 : b === 'index' ? 1 : a.localeCompare(b)));
  return [...keys, ...new Set(unlisted)];
}

/**
 * Collects the visible pages of a folder, recursing into subfolders.
 *
 * @param {string} dir Absolute folder path.
 * @returns {Promise<{title: string, url: string, description: string}[]>} Pages in sidebar order.
 */
async function collectPages(dir) {
  const meta = await loadMeta(dir);
  const pages = [];
  for (const key of orderedKeys(dir, meta)) {
    const entry = entryOf(meta[key]);
    if (entry.display === 'hidden' || entry.type === 'separator') continue;
    if (typeof entry.href === 'string' && /^[a-z]+:/i.test(entry.href)) continue;
    const file = pageFile(dir, key);
    if (file) {
      const frontmatter = readFrontmatter(file);
      const title = plainTitle(String(entry.title ?? '')) || plainTitle(frontmatter.title ?? '') || key;
      pages.push({ title, url: pageUrl(file), description: frontmatter.description ?? '' });
    } else if (existsSync(join(dir, key)) && statSync(join(dir, key)).isDirectory()) {
      pages.push(...(await collectPages(join(dir, key))));
    }
    // Anything else is a link-only entry (an href to a page listed elsewhere).
  }
  return pages;
}

/**
 * Formats one section of the file.
 *
 * @param {string} heading The section heading.
 * @param {{title: string, url: string, description: string}[]} pages The pages in it.
 * @returns {string} Markdown for the section.
 */
function section(heading, pages) {
  const lines = pages.map((p) => `- [${p.title}](${p.url})${p.description ? `: ${p.description}` : ''}`);
  return `## ${heading}\n\n${lines.join('\n')}\n`;
}

/**
 * Builds the full llms.txt text from content/.
 *
 * Top-level pages go in an "Overview" section; each top-level folder becomes a
 * section titled as in the root _meta.js, with its subfolders flattened in.
 *
 * @returns {Promise<string>} The file contents.
 */
async function buildLlmsTxt() {
  const rootMeta = await loadMeta(CONTENT_DIR);
  const overview = [];
  const sections = [];
  for (const key of orderedKeys(CONTENT_DIR, rootMeta)) {
    const entry = entryOf(rootMeta[key]);
    if (entry.display === 'hidden' || entry.type === 'separator') continue;
    if (typeof entry.href === 'string' && /^[a-z]+:/i.test(entry.href)) continue;
    const file = pageFile(CONTENT_DIR, key);
    const folder = join(CONTENT_DIR, key);
    if (file) {
      const frontmatter = readFrontmatter(file);
      const title = plainTitle(String(entry.title ?? '')) || plainTitle(frontmatter.title ?? '') || key;
      overview.push({ title, url: pageUrl(file), description: frontmatter.description ?? '' });
    } else if (existsSync(folder) && statSync(folder).isDirectory()) {
      const pages = await collectPages(folder);
      if (pages.length) sections.push(section(plainTitle(String(entry.title ?? '')) || key, pages));
    }
  }
  const parts = [HEADER];
  if (overview.length) parts.push(section('Overview', overview));
  parts.push(...sections);
  return parts.join('\n');
}

async function main() {
  const text = await buildLlmsTxt();
  if (process.argv.includes('--print')) {
    process.stdout.write(text);
    return;
  }
  const current = existsSync(OUTPUT) ? readFileSync(OUTPUT, 'utf8') : '';
  if (process.argv.includes('--check')) {
    if (current !== text) {
      console.error('public/llms.txt is out of date. Run `npm run llms` in docs/ and commit the result.');
      process.exit(1);
    }
    console.log('public/llms.txt is up to date.');
    return;
  }
  if (current === text) {
    console.log('public/llms.txt is already up to date.');
    return;
  }
  writeFileSync(OUTPUT, text);
  console.log(`Wrote ${relative(DOCS_ROOT, OUTPUT)}.`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
