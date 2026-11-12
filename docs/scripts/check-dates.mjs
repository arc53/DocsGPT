#!/usr/bin/env node
// Checks the `lastUpdated: YYYY-MM-DD` frontmatter date every docs page carries.
// The date is shown on the page and becomes the sitemap's lastmod and the
// structured data's dateModified, so it must be present, real, and not in the
// future. It fails on any of those.
//
// With --base <git ref> it also compares each page against that ref and fails
// when a page that already existed there has a different lastUpdated. A pull
// request leaves the date of an existing page alone: the "Generated docs"
// workflow dates pages on main after the merge (scripts/sync-dates.mjs), so
// two pull requests that change the same page no longer conflict on that line.
// A new page still arrives with its own date.
//
// On an existing page whose date is unchanged but whose text a reader sees
// changed (readerText), it prints a notice and does not fail: the page will be
// dated with the day of the merge, unless [keep-date] is in the pull request
// title (read from PR_TITLE) or in the subject of every commit since --base
// that changes the page (sync-dates.mjs keepsDate makes the same decision on
// main). A rebase merge brings no pull request title to main, so there only the
// commit subjects count.
//
//   node scripts/check-dates.mjs                 check every page
//   node scripts/check-dates.mjs --base HEAD^1   also compare each existing page with HEAD^1

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

import { KEEP_MARKER, keepsDate, PAGE_RE, readerText, readLastUpdated } from './sync-dates.mjs';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONTENT_DIR = join(DOCS_ROOT, 'content');
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
 * @param {'error' | 'warning' | 'notice'} level The annotation level.
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

/**
 * Lists the subject line of every commit since a ref that changed a file, merges left out.
 *
 * @param {string} ref The git ref the pull request is compared against.
 * @param {string} file The path, relative to the repository root.
 * @returns {string[]} The subjects, newest first.
 */
function subjectsSince(ref, file) {
  const out = execFileSync('git', ['log', '--no-merges', '--format=%s', `${ref}..HEAD`, '--', file], {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: 'pipe',
  });
  return out.split('\n').filter(Boolean);
}

const baseIndex = process.argv.indexOf('--base');
const base = baseIndex === -1 ? undefined : process.argv[baseIndex + 1];
if (baseIndex !== -1 && !base) {
  console.error('--base needs a git ref');
  process.exit(2);
}

if (base) {
  // An unreadable ref would make every page look new, and so pass.
  try {
    execFileSync('git', ['rev-parse', '--verify', '--quiet', `${base}^{commit}`], { cwd: DOCS_ROOT, stdio: 'pipe' });
  } catch {
    console.error(`--base ${base} is not a commit in this clone`);
    process.exit(2);
  }
}

// A day of slack, so an author ahead of UTC can date a page with their own today.
const latest = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
const repoRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: DOCS_ROOT, encoding: 'utf8' }).trim();

let errors = 0;
let redated = 0;
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
  if (before === undefined) continue;
  const previous = readLastUpdated(before);
  if (previous !== undefined && previous !== value) {
    report(
      'error',
      file,
      `has lastUpdated ${value}, changed from ${previous}. Put ${previous} back: pages are dated on main after ` +
        'the merge, so pull requests leave the date of an existing page alone (see docs/AGENTS.md).',
    );
    redated += 1;
  } else if (readerText(before) !== readerText(text)) {
    const kept = keepsDate({ mergeMessage: process.env.PR_TITLE, subjects: subjectsSince(base, file) });
    if (!kept) {
      report(
        'notice',
        file,
        'changed for readers, so after the merge it will be dated with the day of the merge. If a reader ' +
          `would not notice the change, put ${KEEP_MARKER} in the pull request title or in the subject line of ` +
          'each commit that changes the page.',
      );
    }
  }
}

const pages = listPages(CONTENT_DIR).length;
if (errors || redated) {
  if (errors) console.error(`${errors} of ${pages} pages have a missing or invalid lastUpdated date.`);
  if (redated) console.error(`${redated} existing page(s) had their lastUpdated date changed.`);
  process.exit(1);
}
console.log(`lastUpdated is valid on all ${pages} pages.`);
