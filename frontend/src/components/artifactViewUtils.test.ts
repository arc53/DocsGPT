import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ARTIFACT_URL_ENVELOPE_MIME,
  buildPreviewDocument,
  bytesPreviewModeForMime,
  displayFilename,
  filenameFromContentDisposition,
  findCurrentVersion,
  formatBytes,
  isDocumentArtifact,
  MAX_INLINE_TEXT_BYTES,
  PREVIEW_CSP,
  PREVIEW_CSP_MERMAID,
  previewModeForKind,
  readPresignedUrlEnvelope,
  sortVersionsDesc,
  triggerResponseDownload,
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

describe('bytesPreviewModeForMime', () => {
  it('routes html/svg markup to the sandboxed iframe', () => {
    expect(bytesPreviewModeForMime('text/html')).toBe('iframe-html');
    expect(bytesPreviewModeForMime('image/svg+xml')).toBe('iframe-svg');
  });

  it('routes raster images to the inline image renderer', () => {
    expect(bytesPreviewModeForMime('image/png')).toBe('image');
    expect(bytesPreviewModeForMime('image/jpeg')).toBe('image');
    expect(bytesPreviewModeForMime('image/gif')).toBe('image');
    expect(bytesPreviewModeForMime('image/webp')).toBe('image');
  });

  it('routes markdown to the markdown renderer and other text to plain', () => {
    expect(bytesPreviewModeForMime('text/markdown')).toBe('text-markdown');
    expect(bytesPreviewModeForMime('text/x-markdown')).toBe('text-markdown');
    expect(bytesPreviewModeForMime('text/plain')).toBe('text-plain');
    expect(bytesPreviewModeForMime('text/csv')).toBe('text-plain');
    expect(bytesPreviewModeForMime('application/json')).toBe('text-plain');
    expect(bytesPreviewModeForMime('text/whatever')).toBe('text-plain');
  });

  it('ignores charset parameters and casing on the mime', () => {
    expect(bytesPreviewModeForMime('TEXT/HTML; charset=utf-8')).toBe(
      'iframe-html',
    );
    expect(bytesPreviewModeForMime('text/plain;charset=UTF-8')).toBe(
      'text-plain',
    );
  });

  it('routes office docs / pdf / unknown to the download card', () => {
    expect(
      bytesPreviewModeForMime(
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ),
    ).toBe('card');
    expect(bytesPreviewModeForMime('application/pdf')).toBe('card');
    expect(bytesPreviewModeForMime('application/zip')).toBe('card');
  });

  it('falls back to kind when the mime is missing or octet-stream', () => {
    expect(bytesPreviewModeForMime(null, 'html')).toBe('iframe-html');
    expect(bytesPreviewModeForMime(undefined, 'svg')).toBe('iframe-svg');
    expect(bytesPreviewModeForMime('application/octet-stream', 'image')).toBe(
      'image',
    );
    expect(bytesPreviewModeForMime('', 'code')).toBe('text-plain');
    expect(bytesPreviewModeForMime('', 'data')).toBe('text-plain');
  });

  it('cards an unknown kind with no usable mime', () => {
    expect(bytesPreviewModeForMime(null, 'presentation')).toBe('card');
    expect(bytesPreviewModeForMime(null, null)).toBe('card');
  });

  it('exposes a sane inline text bound', () => {
    expect(MAX_INLINE_TEXT_BYTES).toBeGreaterThan(0);
    expect(MAX_INLINE_TEXT_BYTES).toBeLessThanOrEqual(1024 * 1024);
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

describe('readPresignedUrlEnvelope', () => {
  const envelope = (body: unknown, contentType = ARTIFACT_URL_ENVELOPE_MIME) =>
    new Response(JSON.stringify(body), {
      headers: { 'Content-Type': contentType },
    });

  it('extracts the presigned url from the s3 JSON envelope', async () => {
    const url = await readPresignedUrlEnvelope(
      envelope({ success: true, url: 'https://signed.example/x?sig=1' }),
    );
    expect(url).toBe('https://signed.example/x?sig=1');
  });

  it('returns null for a byte stream and leaves the body readable', async () => {
    const res = new Response('<p>hi</p>', {
      headers: { 'Content-Type': 'text/html' },
    });
    expect(await readPresignedUrlEnvelope(res)).toBeNull();
    expect(await res.text()).toBe('<p>hi</p>');
  });

  it('returns null for a JSON artifact whose bytes are not the envelope', async () => {
    const res = envelope({ foo: 1 }, 'application/json');
    expect(await readPresignedUrlEnvelope(res)).toBeNull();
    // clone() was used to peek, so the original body is still consumable.
    expect(await res.json()).toEqual({ foo: 1 });
  });

  it('ignores an attacker JSON artifact that mimics the envelope body', async () => {
    // Under URL_STRATEGY=backend a `data` artifact is streamed with its own
    // application/json content-type; even with the exact envelope shape it must
    // NOT be treated as a redirect (open-redirect gadget) — only the vendor
    // media type marks a real envelope.
    const res = envelope(
      { success: true, url: 'https://attacker.example/phish' },
      'application/json',
    );
    expect(await readPresignedUrlEnvelope(res)).toBeNull();
    expect(await res.json()).toEqual({
      success: true,
      url: 'https://attacker.example/phish',
    });
  });

  it('rejects a non-http(s) url in the envelope', async () => {
    expect(
      await readPresignedUrlEnvelope(
        envelope({ success: true, url: 'javascript:alert(1)' }),
      ),
    ).toBeNull();
    expect(
      await readPresignedUrlEnvelope(envelope({ success: true, url: '' })),
    ).toBeNull();
  });
});

describe('triggerResponseDownload', () => {
  let anchors: HTMLAnchorElement[];

  beforeEach(() => {
    anchors = [];
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const orig = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = orig(tag);
      if (String(tag).toLowerCase() === 'a') {
        vi.spyOn(el as HTMLAnchorElement, 'click').mockImplementation(
          () => undefined,
        );
        anchors.push(el as HTMLAnchorElement);
      }
      return el;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns false for a non-OK response', async () => {
    const res = new Response('', { status: 500 });
    expect(await triggerResponseDownload(res, 'f.bin')).toBe(false);
  });

  it('navigates top-level to the presigned url for the s3 envelope', async () => {
    const res = new Response(
      JSON.stringify({ success: true, url: 'https://signed.example/x' }),
      { headers: { 'Content-Type': ARTIFACT_URL_ENVELOPE_MIME } },
    );
    expect(await triggerResponseDownload(res, 'f.bin')).toBe(true);
    // No blob path for the presigned envelope.
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    const anchor = anchors.at(-1)!;
    expect(anchor.href).toBe('https://signed.example/x');
    expect(anchor.target).toBe('_blank');
    expect(anchor.click).toHaveBeenCalled();
  });

  it('saves streamed bytes via a blob url for the backend strategy', async () => {
    const res = new Response('BINARY', {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': 'attachment; filename="deck.pptx"',
      },
    });
    expect(await triggerResponseDownload(res, 'fallback.bin')).toBe(true);
    expect(URL.createObjectURL).toHaveBeenCalled();
    const anchor = anchors.at(-1)!;
    expect(anchor.download).toBe('deck.pptx');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
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
