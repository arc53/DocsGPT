import { describe, expect, it } from 'vitest';

import {
  getFolderName,
  getUploadPath,
  hasAcceptedExtension,
  isHiddenUpload,
} from './folderUpload';

/** A File as the folder picker (webkitRelativePath) or a drop (path) gives it. */
function fileAt(
  name: string,
  where: { webkitRelativePath?: string; path?: string } = {},
): File {
  const file = new File(['x'], name);
  if (where.webkitRelativePath !== undefined)
    Object.defineProperty(file, 'webkitRelativePath', {
      value: where.webkitRelativePath,
    });
  if (where.path !== undefined)
    Object.defineProperty(file, 'path', { value: where.path });
  return file;
}

describe('getUploadPath', () => {
  it('uses the path inside a picked folder', () => {
    const file = fileAt('a.md', { webkitRelativePath: 'docs/guide/a.md' });
    expect(getUploadPath(file)).toBe('docs/guide/a.md');
  });

  it('uses the path of a file from a dropped folder, without the leading slash', () => {
    const file = fileAt('a.md', { path: '/docs/guide/a.md' });
    expect(getUploadPath(file)).toBe('docs/guide/a.md');
  });

  it('keeps a loose file to its name', () => {
    expect(getUploadPath(fileAt('a.md'))).toBe('a.md');
    expect(getUploadPath(fileAt('a.md', { path: './a.md' }))).toBe('a.md');
  });

  it('never sends dot or dot-dot parts', () => {
    const file = fileAt('x.md', { path: '../docs/./x.md' });
    expect(getUploadPath(file)).toBe('docs/x.md');
  });
});

describe('getFolderName', () => {
  it('names the top folder of a folder file', () => {
    const file = fileAt('a.md', { webkitRelativePath: 'Handbook/guide/a.md' });
    expect(getFolderName(file)).toBe('Handbook');
  });

  it('has none for a loose file', () => {
    expect(getFolderName(fileAt('a.md', { path: './a.md' }))).toBeUndefined();
  });
});

describe('isHiddenUpload', () => {
  it('flags hidden files and anything inside a hidden folder', () => {
    expect(
      isHiddenUpload(fileAt('HEAD', { webkitRelativePath: 'repo/.git/HEAD' })),
    ).toBe(true);
    expect(isHiddenUpload(fileAt('.env', { path: '/repo/.env' }))).toBe(true);
    expect(
      isHiddenUpload(fileAt('a.md', { webkitRelativePath: 'repo/a.md' })),
    ).toBe(false);
  });
});

describe('hasAcceptedExtension', () => {
  const accept = { 'text/x-markdown': ['.md'], 'application/pdf': ['.pdf'] };

  it('accepts listed extensions in any case', () => {
    expect(hasAcceptedExtension(fileAt('a.md'), accept)).toBe(true);
    expect(hasAcceptedExtension(fileAt('B.PDF'), accept)).toBe(true);
  });

  it('refuses other or missing extensions', () => {
    expect(hasAcceptedExtension(fileAt('setup.exe'), accept)).toBe(false);
    expect(hasAcceptedExtension(fileAt('Makefile'), accept)).toBe(false);
  });
});
