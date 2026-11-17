#!/usr/bin/env node
// Fails when a pull request changes a file that is generated on main.
//
// These files are rebuilt from the code and the docs sidebar by the "Generated
// docs" workflow after every merge, which puts them in its own pull request.
// A pull request that carried its own copy conflicted with every other pull
// request that did the same, so they stay out of pull requests altogether.
// Adding one for the first time is fine; changing or deleting one is not.
//
//   node scripts/check-generated.mjs --base HEAD^1

import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DOCS_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// Path (from the repository root) -> the command that writes it.
export const GENERATED = {
  'docs/data/swagger.json': 'python -m docsgpt.api.reference --write',
  'docs/data/mcp-presets.json': 'python -m docsgpt.connectors.reference --write',
  'docs/content/Deploying/Settings-Reference.mdx': 'python -m docsgpt.core.settings.reference --write',
  'docs/public/llms.txt': 'npm run llms',
};

const baseIndex = process.argv.indexOf('--base');
const base = baseIndex === -1 ? undefined : process.argv[baseIndex + 1];
if (!base) {
  console.error('usage: node scripts/check-generated.mjs --base <git ref>');
  process.exit(2);
}

const git = (args) => execFileSync('git', args, { cwd: DOCS_ROOT, encoding: 'utf8' });
const repoRoot = git(['rev-parse', '--show-toplevel']).trim();
// M, D, R, T: everything but a first-time add.
const changed = execFileSync(
  'git',
  ['diff', '--name-only', '--no-renames', '--diff-filter=MDT', base, 'HEAD', '--', ...Object.keys(GENERATED)],
  { cwd: repoRoot, encoding: 'utf8' },
)
  .split('\n')
  .filter(Boolean);

for (const file of changed) {
  const message =
    `is generated on main after the merge (${GENERATED[file]}); ` +
    `take it out of this pull request: git checkout <base branch> -- ${file}`;
  if (process.env.GITHUB_ACTIONS) console.log(`::error file=${file}::${file} ${message}`);
  else console.log(`error: ${file} ${message}`);
}
if (changed.length) {
  console.error(`${changed.length} generated file(s) changed. See docs/AGENTS.md, "Generated files".`);
  process.exit(1);
}
console.log('No generated file was changed.');
