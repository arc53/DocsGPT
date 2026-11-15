#!/usr/bin/env node
// Keeps the keys of every src/locale/*.json file in order, at every level.
//
// New keys used to go at the end of a section, so two pull requests that each
// added a string to the same section conflicted in all eight files. In sorted
// files a new key goes where its name puts it, and two additions rarely meet.
//
// The order is by UTF-16 code unit (what `<` gives for strings): uppercase
// before lowercase, the same on every machine and in every locale.
//
//   node scripts/sort-locales.mjs          sort the files in place
//   node scripts/sort-locales.mjs --check  exit 1 if a file is not sorted

import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const LOCALE_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  '..',
  'src',
  'locale',
);

/**
 * Compares two keys by UTF-16 code unit.
 *
 * @param {string} a One key.
 * @param {string} b Another key.
 * @returns {number} Negative, zero or positive, as Array.prototype.sort expects.
 */
export function compareKeys(a, b) {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/**
 * Returns a copy of a locale tree with its keys sorted at every level.
 *
 * @param {unknown} value A locale tree, or one of its strings.
 * @returns {unknown} The same data, keys in order.
 */
export function sortTree(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.keys(value)
      .sort(compareKeys)
      .map((key) => [key, sortTree(value[key])]),
  );
}

/**
 * Renders a locale tree the way the files store it.
 *
 * @param {unknown} tree A locale tree.
 * @returns {string} Two-space JSON with a trailing newline.
 */
export function render(tree) {
  return `${JSON.stringify(tree, null, 2)}\n`;
}

/**
 * Sorts or checks every locale file.
 *
 * @param {{ check: boolean }} options With `check`, nothing is written.
 * @returns {string[]} The files that were (or, with `check`, are) out of order.
 */
export function run({ check }) {
  const unsorted = [];
  for (const name of readdirSync(LOCALE_DIR).sort()) {
    if (!name.endsWith('.json')) continue;
    const path = join(LOCALE_DIR, name);
    const text = readFileSync(path, 'utf8');
    const sorted = render(sortTree(JSON.parse(text)));
    if (sorted === text) continue;
    unsorted.push(name);
    if (!check) writeFileSync(path, sorted);
  }
  return unsorted;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const check = process.argv.includes('--check');
  const unsorted = run({ check });
  if (check && unsorted.length) {
    console.error(
      `Not sorted: ${unsorted.join(', ')}. Run "npm run locale:sort" in frontend/.`,
    );
    process.exit(1);
  }
  console.log(
    unsorted.length
      ? `Sorted ${unsorted.join(', ')}.`
      : 'Every locale file is sorted.',
  );
}
