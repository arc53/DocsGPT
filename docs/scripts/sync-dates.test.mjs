// Run with `npm test` in docs/ (node --test). Each test builds a small git
// repository shaped like main: a baseline commit, then merges and pushes.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

import { keepsDate, planDates, readerText, readLastUpdated, setLastUpdated } from './sync-dates.mjs';

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

/**
 * Merges a branch made of the given commits into main, the way a pull request
 * lands with a merge commit: GitHub's message carries the pull request's title.
 */
function mergePullRequest(commits, title = 'docs: a change') {
  git('switch', '-q', '-c', 'feature');
  for (const [message, files] of commits) commit(message, files);
  git('switch', '-q', 'main');
  git('merge', '-q', '--no-ff', '-m', `Merge pull request #1 from arc53/feature\n\n${title}`, 'feature');
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

test('a change that set the date to the day it merged is left alone', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  // branch commit 03-02, merge 03-03
  mergePullRequest([['docs: new step', { [PAGE]: page('2026-03-03', 'New.') }]]);

  assert.deepEqual(planDates({ root, since }), []);
});

test('a change that set an older date is not dated with the day it merged', () => {
  // The settings reference: its generator sets the date when the content changes,
  // and the bot's pull request merges days later.
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([['Update the generated docs files', { [PAGE]: page('2026-03-02', 'New.') }]]);

  assert.deepEqual(planDates({ root, since }), []);
});

test('a stale generated-docs merge after a content change still leaves the change to date', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: first change', { [PAGE]: page('2026-01-01', 'First.') });
  // The bot opens its pull request (dating the first change) before the second change merges.
  git('switch', '-q', '-c', 'generated-docs');
  commit('Update the generated docs files', { [PAGE]: page('2026-03-02', 'First.') });
  git('switch', '-q', 'main');
  const change = commit('docs: second change', { [PAGE]: page('2026-01-01', 'Second.') });
  git('merge', '-q', '--no-ff', '-m', 'Merge pull request #2 from arc53/generated-docs', 'generated-docs');

  // second change 03-04; the merge (03-05) set 2026-03-02, older than itself
  assert.deepEqual(planDates({ root, since }), [{ file: PAGE, from: '2026-03-02', to: '2026-03-04', commit: change }]);
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

test('a whitespace-only change does not date the page', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'One two.') });
  commit('docs: reflow', { [PAGE]: `${page('2026-01-01', 'One\n  two.')}\n` });

  assert.deepEqual(planDates({ root, since }), []);
});

test('a frontmatter-only change does not date the page', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: better description', {
    [PAGE]: page('2026-01-01', 'Old.').replace('title: Guide', 'title: The Guide\ndescription: All of it.'),
  });

  assert.deepEqual(planDates({ root, since }), []);
});

test('a changed word in the body dates the page', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'One two.') });
  commit('docs: wording', { [PAGE]: page('2026-01-01', 'One three.') });

  assert.equal(planDates({ root, since }).length, 1);
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

test('a merge whose pull request title says [keep-date] is passed over', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([['docs: wording', { [PAGE]: page('2026-01-01', 'New.') }]], 'docs: typos [keep-date]');

  assert.deepEqual(planDates({ root, since }), []);
});

test('[keep-date] in a commit body does not count', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  mergePullRequest([['docs: wording\n\nReaders will not notice. [keep-date]', { [PAGE]: page('2026-01-01', 'New.') }]]);

  assert.equal(planDates({ root, since }).length, 1);
});

test('a squash merge whose title says [keep-date] is passed over', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: typos [keep-date] (#5)\n\n* docs: typo\n\n* docs: another', { [PAGE]: page('2026-01-01', 'New.') });

  assert.deepEqual(planDates({ root, since }), []);
});

test('[keep-date] on one commit listed in a squash merge body does not cover the squash', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: new step (#5)\n\n* docs: new step\n\n* docs: typo [keep-date]', { [PAGE]: page('2026-01-01', 'New.') });

  assert.equal(planDates({ root, since }).length, 1);
});

test('a kept-date fix on top of an undated change still leaves the change to date', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  const change = commit('docs: new step', { [PAGE]: page('2026-01-01', 'New step.') });
  commit('docs: typo [keep-date]', { [PAGE]: page('2026-01-01', 'New step!') });

  assert.deepEqual(planDates({ root, since }), [{ file: PAGE, from: '2026-01-01', to: '2026-03-02', commit: change }]);
});

test('the walk stops at the last entry that set the date to its own day or later', () => {
  const since = commit('baseline', { [PAGE]: page('2026-01-01', 'Old.') });
  commit('docs: undated change', { [PAGE]: page('2026-01-01', 'Change one.') });
  commit('docs: date it by hand', { [PAGE]: page('2026-03-03', 'Change one.') });
  // A stale date on top is passed over; the walk stops at 03-03 and never reaches the 03-02 change.
  commit('Update the generated docs files', { [PAGE]: page('2026-01-15', 'Change one.') });

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

test('keepsDate: the merge message, or every subject', () => {
  assert.equal(keepsDate({ mergeMessage: 'Merge pull request #1\n\nTypos [keep-date]', subjects: ['x'] }), true);
  assert.equal(keepsDate({ subjects: ['a [keep-date]', 'b [keep-date]'] }), true);
  assert.equal(keepsDate({ subjects: ['a [keep-date]', 'b'] }), false);
  assert.equal(keepsDate({ mergeMessage: 'Merge pull request #1', subjects: [] }), false);
  assert.equal(keepsDate({ subjects: [] }), false);
});

test('readerText is the body with its whitespace collapsed', () => {
  assert.equal(readerText('---\ntitle: A\nlastUpdated: 2026-01-01\n---\n\n# Hi\n\n  there\n'), '# Hi there');
  assert.equal(readerText('No frontmatter\r\n here.'), 'No frontmatter here.');
});
