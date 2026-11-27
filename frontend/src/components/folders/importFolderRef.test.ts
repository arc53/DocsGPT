import { describe, expect, it } from 'vitest';

import { importFolderRefs } from './importFolderRef';

const entry = (
  name: string,
  extra: { key?: string; path_key?: string | null } = {},
) => ({ name, type: 'folder', ...extra });

describe('importFolderRefs', () => {
  it('names each folder entry by its key', () => {
    const entries = [
      entry('Ops', { key: 'folder-0', path_key: 'Carriers/Ops' }),
      entry('Ops', { key: 'folder-1', path_key: 'Customs/Ops' }),
    ];
    expect(importFolderRefs(entries)).toEqual(['folder-0', 'folder-1']);
  });

  it('falls back to the path, then the name, when the key is shared', () => {
    const entries = [
      entry('Ops', { key: 'k', path_key: 'Carriers/Ops' }),
      entry('Rates', { key: 'k', path_key: null }),
    ];
    expect(importFolderRefs(entries)).toEqual(['Carriers/Ops', 'Rates']);
  });

  it('reads an older plan without keys by name', () => {
    expect(importFolderRefs([entry('Ops'), entry('Rates')])).toEqual([
      'Ops',
      'Rates',
    ]);
  });

  it('gives no reference to an entry nothing names alone', () => {
    // Two entries with one name and no key or path: the server would ignore
    // either mapping, so neither can be picked by hand.
    expect(importFolderRefs([entry('Ops'), entry('Ops')])).toEqual([
      null,
      null,
    ]);
  });
});
