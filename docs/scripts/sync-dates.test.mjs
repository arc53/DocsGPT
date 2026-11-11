// Run with `npm test` in docs/ (node --test). Each test builds a small git
// repository shaped like main: a baseline commit, then merges and pushes.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

import { planDates, readLastUpdated, setLastUpdated } from './sync-dates.mjs';

const PAGE = 'docs/content/guide.mdx';
let root;
let clock;

const page = (date, body) => `---\ntitle: Guide\nlastUpdated: ${date}\n---\n\n${body}\n`;

function git(...args) {
  // Each commit is a day after the one before, starting 2026-03-01 (UTC).
  const when = `2026-03-${String(clock).padStart(2, '0')}T12:00:00Z`;
  return execFileSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, GIT_AUTHOR_DATE: when, GIT_COMMITTER_DATE: when },
  }).trim();
}

function commit(message, files) {
  for (const [file, text] of Object.entries(files)) {
    mkdirSync(dirname(join(root, file)), { recursive: true });
    writeFileSync(join(root, file), text);
  }
  git('add', '-A');
  git('commit', '-q', '-m', message);
  clock += 1;
  return git('rev-parse', 'HEAD');
}

/** Merges a branch made of the given commits into main, the way a pull request lands. */
function mergePullRequest(commits) {
  git('switch', '-q', '-c', 'feature');
  for (const [message, files] of commits) commit(message, files);
  git('switch', '-q', 'main');
  git('merge', '-q', '--no-ff', '-m', 'Merge pull request #1', 'feature');
  clock += 1;
  git('branch', '-q', '-D', 'feature');
  return git('rev-parse', 'HEAD');
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'sync-dates-'));
  clock = 1;
  git('init', '-q', '-b', 'main');
  git('config', 'user.email', 'test@example.com');
  git('config', 'user.name', 'Test');
  git('config', 'commit.gpgsign', 'false');
});

afterEach(() => rmSync(root, { recursive: true, force: true }));

test('a merged content change dates the page with the day it merged', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  const merge = mergePullRequest([['docs: new step', { [PAGE]: page('2026-01-01', 'New step.') }]]);

  // baseline 03-01, branch commit 03-02, merge 03-03
  assert.deepEqual(planDates({ root, since }), [{ file: PAGE, from: '2026-01-01', to: '2026-03-03', commit: merge }]);
});

test('a direct push dates the page too', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: new step', { [PAGE]: page('2026-01-01', 'New.') });

  assert.equal(planDates({ root, since })[0].to, '2026-03-02');
});

test('a change that set the date itself is left alone', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([['docs: new step', { [PAGE]: page('2026-02-02', 'New.') }]]);

  assert.deepEqual(planDates({ root, since }), []);
});

test('a new page keeps the date it arrived with', () => {
  const since = commit('baseline', { 'README.md': 'x' });
  mergePullRequest([['docs: new page', { [PAGE]: page('2026-02-02', 'Hello.') }]]);

  assert.deepEqual(planDates({ root, since }), []);
});

test('content that changed before the baseline is not re-dated', () => {
  commit('first', { [PAGE]: page('2026-01-01', 'Old.') });
  const since = commit('typo, long ago', { [PAGE]: page('2026-01-01', 'Older.') });
  commit('unrelated', { 'README.md': 'x' });

  assert.deepEqual(planDates({ root, since }), []);
});

test('a pull request whose commits all say [keep-date] is passed over', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([
    ['docs: fix a typo [keep-date]', { [PAGE]: page('2026-01-01', 'Olde.') }],
    ['docs: and another [keep-date]', { [PAGE]: page('2026-01-01', 'Older.') }],
  ]);

  assert.deepEqual(planDates({ root, since }), []);
});

test('one commit without [keep-date] is enough to date the page', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([
    ['docs: fix a typo [keep-date]', { [PAGE]: page('2026-01-01', 'Olde.') }],
    ['docs: new step', { [PAGE]: page('2026-01-01', 'New step.') }],
  ]);

  assert.equal(planDates({ root, since }).length, 1);
});

test('[keep-date] on another page in the pull request does not cover this one', () => {
  const other = 'docs/content/other.mdx';
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.'), [other]: page('2026-01-01', 'Old.') });
  mergePullRequest([
    ['docs: typo [keep-date]', { [other]: page('2026-01-01', 'Olde.') }],
    ['docs: new step', { [PAGE]: page('2026-01-01', 'New step.') }],
  ]);

  assert.deepEqual(planDates({ root, since }).map((move) => move.file), [PAGE]);
});

test('a kept-date fix on top of an undated change still leaves the change to date', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  const change = commit('docs: new step', { [PAGE]: page('2026-01-01', 'New step.') });
  commit('docs: typo [keep-date]', { [PAGE]: page('2026-01-01', 'New step!') });

  assert.deepEqual(planDates({ root, since }), [{ file: PAGE, from: '2026-01-01', to: '2026-03-02', commit: change }]);
});

test('the walk stops at the last entry that set the date', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: undated change', { [PAGE]: page('2026-01-01', 'Change one.') });
  commit('Update the generated docs files', { [PAGE]: page('2026-03-02', 'Change one.') });

  assert.deepEqual(planDates({ root, since }), []);
});

test('a page deleted since is skipped', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: change', { [PAGE]: page('2026-01-01', 'New.') });
  git('rm', '-q', PAGE);
  git('commit', '-q', '-m', 'docs: drop the page');

  assert.deepEqual(planDates({ root, since }), []);
});

test('a date that is already later is not moved back', () => {
  const since = commit('baseline', { [PAGE]: page('2027-01-01', 'Old.') });
  commit('docs: change', { [PAGE]: page('2027-01-01', 'New.') });

  assert.deepEqual(planDates({ root, since }), []);
});

test('files that are not pages are ignored', () => {
  const meta = 'docs/content/_meta.js';
  const since = commit('baseline', { [meta]: 'export default {}' });
  commit('docs: sidebar', { [meta]: 'export default { a: "A" }' });

  assert.deepEqual(planDates({ root, since }), []);
});

test('a baseline missing from the clone is an error, not an empty plan', () => {
  commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });

  assert.throws(() => planDates({ root, since: '1234567890123456789012345678901234567890' }), /full history/);
});

test('setLastUpdated changes only the date line', () => {
  const text = page('2026-01-01', 'Body with lastUpdated: 2020-01-01 in prose.');
  const dated = setLastUpdated(text, '2026-05-05');

  assert.equal(readLastUpdated(dated), '2026-05-05');
  assert.equal(dated, text.replace('lastUpdated: 2026-01-01', 'lastUpdated: 2026-05-05'));
});
