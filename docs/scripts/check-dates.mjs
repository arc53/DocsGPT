#!/usr/bin/env node
// Checks the `lastUpdated: YYYY-MM-DD` frontmatter date every docs page carries.
// The date is shown on the page and becomes the sitemap's lastmod and the
// structured data's dateModified, so it must be present, real, and not in the
// future. It fails on any of those.
//
// With --base <git ref> it also compares each page against that ref and warns
// about pages whose content changed while lastUpdated did not. That is only a
// warning: a typo fix or a link rename shouldn't move the date; a change a
// reader would care about should.
//
//   node scripts/check-dates.mjs                 check every page
//   node scripts/check-dates.mjs --base HEAD^1   also warn about changed, undated pages

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONTENT_DIR = join(DOCS_ROOT, 'content');
const PAGE_RE = /\.mdx?$/;
const FRONTMATTER_RE = /^---\r?\n([\s\S]*?\r?\n)?---/;
const FIELD_RE = /^lastUpdated:[ \t]*(['"]?)(\S*?)\1[ \t]*$/m;
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const IN_CI = Boolean(process.env.GITHUB_ACTIONS);

/**
 * Lists every page file under a folder.
 *
 * @param {string} dir Absolute folder path.
 * @returns {string[]} Absolute page paths.
 */
function listPages(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return listPages(path);
    return PAGE_RE.test(name) ? [path] : [];
  });
}

/**
 * Reads a page's lastUpdated value as written.
 *
 * @param {string} text The page source.
 * @returns {string | undefined} The raw value, or undefined when the field is missing.
 */
function readLastUpdated(text) {
  const block = text.match(FRONTMATTER_RE)?.[1];
  return block?.match(FIELD_RE)?.[2];
}

/**
 * Says what is wrong with a lastUpdated value, if anything.
 *
 * @param {string | undefined} value The raw value.
 * @param {string} latest The latest acceptable date, YYYY-MM-DD.
 * @returns {string | undefined} The problem, or undefined when the date is fine.
 */
function problemWith(value, latest) {
  if (value === undefined) return 'has no `lastUpdated: YYYY-MM-DD` in its frontmatter';
  const parts = value.match(DATE_RE);
  if (!parts) return `has lastUpdated "${value}", which is not YYYY-MM-DD`;
  const [, year, month, day] = parts.map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    return `has lastUpdated ${value}, which is not a real date`;
  }
  if (value > latest) return `has lastUpdated ${value}, which is in the future`;
  return undefined;
}

/**
 * Prints a message, as a GitHub annotation on the file when running in Actions.
 *
 * @param {'error' | 'warning'} level The annotation level.
 * @param {string} file The page path, relative to the repository root.
 * @param {string} message What to say.
 */
function report(level, file, message) {
  if (IN_CI) console.log(`::${level} file=${file}::${message}`);
  else console.log(`${level}: ${file} ${message}`);
}

/**
 * Reads a file as it was at a git ref.
 *
 * @param {string} ref The git ref.
 * @param {string} file The path, relative to the repository root.
 * @returns {string | undefined} The text, or undefined when the file did not exist there.
 */
function readAtRef(ref, file) {
  try {
    return execFileSync('git', ['show', `${ref}:${file}`], { cwd: DOCS_ROOT, encoding: 'utf8', stdio: 'pipe' });
  } catch {
    return undefined;
  }
}

const baseIndex = process.argv.indexOf('--base');
const base = baseIndex === -1 ? undefined : process.argv[baseIndex + 1];
if (baseIndex !== -1 && !base) {
  console.error('--base needs a git ref');
  process.exit(2);
}

// A day of slack, so an author ahead of UTC can date a page with their own today.
const latest = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
const repoRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: DOCS_ROOT, encoding: 'utf8' }).trim();

let errors = 0;
let warnings = 0;
for (const path of listPages(CONTENT_DIR).sort()) {
  const file = relative(repoRoot, path);
  const text = readFileSync(path, 'utf8');
  const value = readLastUpdated(text);
  const problem = problemWith(value, latest);
  if (problem) {
    report('error', file, problem);
    errors += 1;
    continue;
  }
  if (!base) continue;
  const before = readAtRef(base, file);
  if (before === undefined || before === text) continue;
  const undated = (source) => source.replace(FIELD_RE, '');
  if (readLastUpdated(before) === value && undated(before) !== undated(text)) {
    report('warning', file, `changed without moving lastUpdated (still ${value}); bump it if readers would care`);
    warnings += 1;
  }
}

const pages = listPages(CONTENT_DIR).length;
if (errors) {
  console.error(`${errors} of ${pages} pages have a missing or invalid lastUpdated date.`);
  process.exit(1);
}
console.log(`lastUpdated is valid on all ${pages} pages${warnings ? `; ${warnings} changed page(s) kept their date` : ''}.`);
