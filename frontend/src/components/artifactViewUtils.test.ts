import { describe, expect, it } from 'vitest';

import {
  buildPreviewDocument,
  displayFilename,
  filenameFromContentDisposition,
  findCurrentVersion,
  formatBytes,
  isDocumentArtifact,
  PREVIEW_CSP,
  PREVIEW_CSP_MERMAID,
  previewModeForKind,
  sortVersionsDesc,
  type ArtifactVersion,
} from './artifactViewUtils';

const version = (
  n: number,
  extra: Partial<ArtifactVersion> = {},
): ArtifactVersion => ({
  version: n,
  mime_type: null,
  filename: null,
  size: null,
  sha256: null,
  preview_text: null,
  produced_by: null,
  created_at: null,
  ...extra,
});

describe('isDocumentArtifact', () => {
  it('accepts the generalized document shape', () => {
    expect(isDocumentArtifact({ id: 'a', kind: 'html', versions: [] })).toBe(
      true,
    );
  });

  it('rejects the legacy notes/todo shape', () => {
    expect(isDocumentArtifact({ artifact_type: 'note', data: {} })).toBe(false);
  });

  it('rejects nullish / non-objects', () => {
    expect(isDocumentArtifact(null)).toBe(false);
    expect(isDocumentArtifact('x')).toBe(false);
  });
});

describe('previewModeForKind', () => {
  it('maps html/svg/mermaid to the sandboxed frame', () => {
    expect(previewModeForKind('html')).toBe('frame');
    expect(previewModeForKind('svg')).toBe('frame');
    expect(previewModeForKind('mermaid')).toBe('frame');
  });

  it('maps office kinds and pdf to a download card', () => {
    expect(previewModeForKind('document')).toBe('card');
    expect(previewModeForKind('spreadsheet')).toBe('card');
    expect(previewModeForKind('presentation')).toBe('card');
    expect(previewModeForKind('pdf')).toBe('card');
    expect(previewModeForKind('file')).toBe('card');
  });

  it('maps code/data and unknown kinds to text', () => {
    expect(previewModeForKind('code')).toBe('text');
    expect(previewModeForKind('data')).toBe('text');
    expect(previewModeForKind('something-new')).toBe('text');
    expect(previewModeForKind(null)).toBe('text');
  });

  it('infers from mime when the kind is coarse', () => {
    expect(previewModeForKind('file', 'image/svg+xml')).toBe('frame');
    expect(previewModeForKind('file', 'application/pdf')).toBe('card');
    expect(previewModeForKind('file', 'image/png')).toBe('image');
    expect(previewModeForKind('image', 'image/jpeg')).toBe('image');
  });
});

describe('sortVersionsDesc', () => {
  it('orders newest-first without mutating the input', () => {
    const input = [version(1), version(3), version(2)];
    const sorted = sortVersionsDesc(input);
    expect(sorted.map((v) => v.version)).toEqual([3, 2, 1]);
    expect(input.map((v) => v.version)).toEqual([1, 3, 2]);
  });
});

describe('findCurrentVersion', () => {
  it('returns the row matching current_version', () => {
    const v = findCurrentVersion({
      current_version: 2,
      versions: [version(1), version(2), version(3)],
    });
    expect(v?.version).toBe(2);
  });

  it('falls back to the highest version when the pointer is missing', () => {
    const v = findCurrentVersion({
      current_version: 9,
      versions: [version(1), version(4), version(2)],
    });
    expect(v?.version).toBe(4);
  });

  it('returns null for no versions', () => {
    expect(findCurrentVersion({ current_version: 1, versions: [] })).toBeNull();
  });
});

describe('formatBytes', () => {
  it('formats across unit boundaries', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(10 * 1024)).toBe('10 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB');
  });

  it('returns empty for missing/invalid sizes', () => {
    expect(formatBytes(null)).toBe('');
    expect(formatBytes(undefined)).toBe('');
    expect(formatBytes(-1)).toBe('');
  });
});

describe('displayFilename', () => {
  it('prefers the version filename, then title, then id', () => {
    expect(
      displayFilename({ id: 'x', title: 'Deck' }, { filename: 'deck.pptx' }),
    ).toBe('deck.pptx');
    expect(displayFilename({ id: 'x', title: 'Deck' }, null)).toBe('Deck');
    expect(displayFilename({ id: 'x', title: null }, { filename: null })).toBe(
      'artifact-x',
    );
  });
});

describe('buildPreviewDocument', () => {
  it('embeds the restrictive CSP and content', () => {
    const doc = buildPreviewDocument('html', '<p>hi</p>');
    expect(doc).toContain(PREVIEW_CSP);
    expect(doc).toContain('<p>hi</p>');
    expect(doc).toContain('Content-Security-Policy');
  });

  it('keeps script-src none in the CSP', () => {
    expect(PREVIEW_CSP).toContain("script-src 'none'");
    expect(PREVIEW_CSP).toContain("default-src 'none'");
    expect(PREVIEW_CSP).not.toContain('allow-same-origin');
  });

  it('does not allow frame-src for non-mermaid kinds', () => {
    expect(PREVIEW_CSP).not.toContain('frame-src');
    const doc = buildPreviewDocument('html', '<p>hi</p>');
    expect(doc).not.toContain('frame-src');
  });

  it('uses the mermaid CSP that permits a data: frame for mermaid', () => {
    const doc = buildPreviewDocument(
      'mermaid',
      '<iframe src="data:..."></iframe>',
    );
    expect(doc).toContain(PREVIEW_CSP_MERMAID);
    expect(PREVIEW_CSP_MERMAID).toContain('frame-src data:');
    // Scripts and origins stay forbidden on the outer document.
    expect(PREVIEW_CSP_MERMAID).toContain("script-src 'none'");
    expect(PREVIEW_CSP_MERMAID).toContain("default-src 'none'");
    expect(PREVIEW_CSP_MERMAID).not.toContain('allow-same-origin');
    expect(PREVIEW_CSP_MERMAID).not.toContain('allow-scripts');
  });
});

describe('filenameFromContentDisposition', () => {
  it('reads the plain quoted filename', () => {
    expect(
      filenameFromContentDisposition('attachment; filename="report.pdf"'),
    ).toBe('report.pdf');
  });

  it('reads and decodes the RFC 5987 filename* form', () => {
    expect(
      filenameFromContentDisposition(
        "attachment; filename*=UTF-8''my%20deck.pptx",
      ),
    ).toBe('my deck.pptx');
  });

  it('returns null when absent', () => {
    expect(filenameFromContentDisposition(null)).toBeNull();
    expect(filenameFromContentDisposition('attachment')).toBeNull();
  });
});
