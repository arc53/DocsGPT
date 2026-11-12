#!/usr/bin/env node
// Moves each page's `lastUpdated` to the day its content last changed on main.
//
// Pull requests leave `lastUpdated` alone on pages that already exist: two
// pull requests that each bumped the same page's date used to conflict on that
// one line. The "Generated docs" workflow runs this on main after a merge and
// puts the new dates in its own pull request, so the dates still live in the
// frontmatter and the site build (on Vercel, from a shallow clone) never asks
// git for them.
//
// For every page it walks main's own history (first parents: one entry per
// merged pull request or direct push), newest first, from HEAD back to the
// baseline below:
//   - the entry that added the page ends the walk: a new page keeps the date
//     it arrived with;
//   - an entry that set the page's lastUpdated to its own day or later ends
//     the walk: the date is current as of that entry, so no older change can
//     be newer;
//   - an entry that set an older date is passed over, and is not taken as a
//     content change either. A "Generated docs" pull request opened before a
//     later content change merged would otherwise hide that change for good,
//     and a generated page, which its generator dates when its content changes,
//     would be dated with the day the bot's pull request merged;
//   - an entry that changed the page's content without setting the date dates
//     the page with that entry's day (UTC), and ends the walk;
//   - an entry whose commits all say [keep-date] is passed over. That is how
//     an author says "readers would not notice": a typo, wording polish, a
//     renamed link target.
//
//   node scripts/sync-dates.mjs           print the dates that would move
//   node scripts/sync-dates.mjs --write   move them
//   node scripts/sync-dates.mjs --since <ref>   walk back to <ref> instead

import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// main when this script arrived. Content changes before it were dated (or
// deliberately left undated) by hand, so the walk never goes past it.
export const BASELINE = 'b5ae12715de289804884c2dc50b3f3b15252f037';
export const KEEP_MARKER = '[keep-date]';

const CONTENT = 'docs/content';
const PAGE_RE = /\.mdx?$/;
const FRONTMATTER_RE = /^---\r?\n([\s\S]*?\r?\n)?---/;
const FIELD_RE = /^lastUpdated:[ \t]*(['"]?)(\S*?)\1[ \t]*$/m;

/**
 * Reads a page's lastUpdated value.
 *
 * @param {string | undefined} text The page source.
 * @returns {string | undefined} The value, or undefined when there is none.
 */
export function readLastUpdated(text) {
  const block = text?.match(FRONTMATTER_RE)?.[1];
  return block?.match(FIELD_RE)?.[2];
}

/**
 * Returns a page with its lastUpdated line set to a day.
 *
 * @param {string} text The page source; it must already carry the field.
 * @param {string} day The new date, YYYY-MM-DD.
 * @returns {string} The page with the new date and nothing else changed.
 */
export function setLastUpdated(text, day) {
  const frontmatter = text.match(FRONTMATTER_RE);
  const block = frontmatter[1].replace(FIELD_RE, `lastUpdated: ${day}`);
  const eol = frontmatter[0].startsWith('---\r\n') ? '\r\n' : '\n';
  return `---${eol}${block}---${text.slice(frontmatter[0].length)}`;
}

const withoutDate = (text) => text.replace(FIELD_RE, '');

/**
 * Builds the git helpers for one repository.
 *
 * @param {string} cwd The repository root.
 * @returns {{ run: (args: string[]) => string, show: (ref: string, file: string) => string | undefined }}
 */
function gitIn(cwd) {
  const run = (args) =>
    execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 1 << 28 });
  const show = (ref, file) => {
    try {
      return run(['show', `${ref}:${file}`]);
    } catch {
      return undefined;
    }
  };
  return { run, show };
}

/**
 * Says whether every commit an entry brought in for a page asks to keep its date.
 *
 * @param {(args: string[]) => string} run The git runner.
 * @param {string} commit A first-parent commit of main.
 * @param {string} file The page path, relative to the repository root.
 * @returns {boolean} True when each commit touching the page carries the marker.
 */
function keepsDate(run, commit, file) {
  const messages = run(['log', '--no-merges', '--format=%B%x00', `${commit}^1..${commit}`, '--', file])
    .split('\0')
    .map((message) => message.trim())
    .filter(Boolean);
  // A direct push or a squash merge is its own single commit.
  const all = messages.length ? messages : [run(['log', '-1', '--format=%B', commit])];
  return all.every((message) => message.includes(KEEP_MARKER));
}

/**
 * Works out which pages need a newer lastUpdated.
 *
 * @param {{ root: string, since?: string, head?: string }} options The repository root, the ref
 *   the walk stops at (the baseline by default) and the ref it starts from.
 * @returns {{ file: string, from: string, to: string, commit: string }[]} One entry per page to re-date.
 */
export function planDates({ root, since = BASELINE, head = 'HEAD' }) {
  const { run, show } = gitIn(root);
  try {
    run(['cat-file', '-e', `${since}^{commit}`]);
  } catch {
    throw new Error(`${since} is not in this clone; sync-dates needs main's full history (fetch-depth: 0).`);
  }

  // Newest first: "<hash> <unix time>" then the pages that entry changed.
  const log = run(['log', '--first-parent', '-m', '--name-only', '--format=%x01%H %ct', `${since}..${head}`, '--', CONTENT]);
  const settled = new Set();
  const moves = [];
  for (const entry of log.split('\x01').slice(1)) {
    const [header, ...names] = entry.split('\n');
    const [commit, time] = header.split(' ');
    const day = new Date(Number(time) * 1000).toISOString().slice(0, 10);
    for (const file of names.filter((name) => PAGE_RE.test(name))) {
      if (settled.has(file)) continue;
      const after = show(commit, file);
      const current = show(head, file);
      if (after === undefined || current === undefined) {
        // Deleted here or since: nothing to date.
        settled.add(file);
        continue;
      }
      const before = show(`${commit}^1`, file);
      if (before === undefined) {
        settled.add(file);
        continue;
      }
      const set = readLastUpdated(after);
      if (readLastUpdated(before) !== set) {
        // A date older than its entry was stale when it merged: look further back.
        if (set !== undefined && set >= day) settled.add(file);
        continue;
      }
      if (withoutDate(before) === withoutDate(after) || keepsDate(run, commit, file)) continue;
      settled.add(file);
      const from = readLastUpdated(current);
      if (from !== undefined && from < day) moves.push({ file, from, to: day, commit });
    }
  }
  return moves.sort((a, b) => a.file.localeCompare(b.file));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
  const sinceIndex = process.argv.indexOf('--since');
  const since = sinceIndex === -1 ? BASELINE : process.argv[sinceIndex + 1];
  if (!since) {
    console.error('--since needs a git ref');
    process.exit(2);
  }
  const write = process.argv.includes('--write');
  let moves;
  try {
    moves = planDates({ root, since });
  } catch (error) {
    console.error(error.message);
    process.exit(2);
  }
  for (const { file, from, to, commit } of moves) {
    console.log(`${file}: ${from} -> ${to} (${commit.slice(0, 9)})`);
    if (write) {
      const path = join(root, file);
      writeFileSync(path, setLastUpdated(readFileSync(path, 'utf8'), to));
    }
  }
  console.log(
    moves.length
      ? `${moves.length} page(s) ${write ? 're-dated' : 'would be re-dated; pass --write to do it'}.`
      : 'Every lastUpdated date is current.',
  );
}
