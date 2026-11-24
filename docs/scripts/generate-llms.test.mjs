import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';

import { buildLlmsTxt } from './generate-llms.mjs';

let root;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'llms-'));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

function write(path, text) {
  const file = join(root, path);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, text);
}

function page(path, title, extra = '') {
  write(path, `---\ntitle: ${title}\n${extra}description: About ${title}.\nlastUpdated: 2026-01-01\n---\n\n# ${title}\n`);
}

function meta(dir, body) {
  write(join(dir, 'meta.js'), `export default ${JSON.stringify(body)};\n`);
}

/** The link lines of the output, without the header. */
async function links() {
  return (await buildLlmsTxt(root)).split('\n').filter((line) => line.startsWith('- ') || line.startsWith('## '));
}

test('lists pages in meta.js order, labelled with sidebarTitle, under the folder title', async () => {
  meta('.', { pages: ['index', 'Guide'] });
  page('index.mdx', 'Home page', 'sidebarTitle: 🏠 Home\n');
  meta('Guide', { title: '📘 Guide', pages: ['b', 'a'] });
  page('Guide/a.mdx', 'Alpha');
  page('Guide/b.mdx', 'Beta', 'sidebarTitle: 🅱️ Bee\n');

  assert.deepEqual(await links(), [
    '## Overview',
    '- [Home](https://docs.docsgpt.cloud/): About Home page.',
    '## Guide',
    '- [Bee](https://docs.docsgpt.cloud/Guide/b): About Beta.',
    '- [Alpha](https://docs.docsgpt.cloud/Guide/a): About Alpha.',
  ]);
});

test('a page meta.js does not list is left out, as in the sidebar', async () => {
  meta('.', { pages: ['Guide'] });
  meta('Guide', { title: 'Guide', pages: ['a'] });
  page('Guide/a.mdx', 'Alpha');
  page('Guide/hidden.mdx', 'Hidden');

  assert.deepEqual(await links(), ['## Guide', '- [Alpha](https://docs.docsgpt.cloud/Guide/a): About Alpha.']);
});

test('"..." lists the remaining pages where it stands, by name, without the excluded ones', async () => {
  meta('.', { pages: ['Guide'] });
  meta('Guide', { title: 'Guide', pages: ['z', '...', 'm', '!skip'] });
  for (const name of ['z', 'm', 'c', 'b', 'skip']) page(`Guide/${name}.mdx`, name.toUpperCase());

  const urls = (await links()).slice(1).map((line) => line.match(/\((.*?)\)/)[1].split('/').pop());
  assert.deepEqual(urls, ['z', 'b', 'c', 'm']);
});

test('separators and links in pages are skipped; folders are flattened into their section', async () => {
  meta('.', { pages: ['Guide'] });
  meta('Guide', { title: 'Guide', pages: ['---Part one---', 'a', '[GitHub](https://github.com)', 'Sub'] });
  page('Guide/a.mdx', 'Alpha');
  meta('Guide/Sub', { title: 'Sub', pages: ['s'] });
  page('Guide/Sub/s.mdx', 'Sigma');

  assert.deepEqual(await links(), [
    '## Guide',
    '- [Alpha](https://docs.docsgpt.cloud/Guide/a): About Alpha.',
    '- [Sigma](https://docs.docsgpt.cloud/Guide/Sub/s): About Sigma.',
  ]);
});

test('a folder without meta.js lists its pages by name, index first', async () => {
  meta('.', { pages: ['Guide'] });
  page('Guide/b.mdx', 'Beta');
  page('Guide/index.mdx', 'Overview');
  page('Guide/a.mdx', 'Alpha');

  const urls = (await links()).slice(1).map((line) => line.match(/\((.*?)\)/)[1]);
  assert.deepEqual(urls, [
    'https://docs.docsgpt.cloud/Guide',
    'https://docs.docsgpt.cloud/Guide/a',
    'https://docs.docsgpt.cloud/Guide/b',
  ]);
});

test('a sidebar file other than meta.js is refused, so the two never disagree', async () => {
  meta('.', { pages: ['Guide'] });
  write('Guide/meta.json', '{"pages": ["a"]}');
  page('Guide/a.mdx', 'Alpha');

  await assert.rejects(buildLlmsTxt(root), /meta\.json/);
});
