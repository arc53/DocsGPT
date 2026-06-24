/**
 * Pure helpers for the document-artifact view: preview-mode mapping, version
 * ordering, sandbox srcdoc/CSP construction, and download-trigger plumbing.
 * Kept free of React so the logic is unit-testable in isolation.
 */

export type ArtifactKind =
  | 'document'
  | 'spreadsheet'
  | 'presentation'
  | 'code'
  | 'html'
  | 'svg'
  | 'mermaid'
  | 'image'
  | 'pdf'
  | 'data'
  | 'file';

export type ArtifactVersion = {
  version: number;
  mime_type: string | null;
  filename: string | null;
  size: number | null;
  sha256: string | null;
  preview_text: string | null;
  produced_by: unknown;
  created_at: string | null;
};

export type DocumentArtifact = {
  id: string;
  kind: string;
  title: string | null;
  current_version: number;
  versions: ArtifactVersion[];
  spec: unknown;
};

/** How the sidebar should render an artifact's current version. */
export type PreviewMode = 'frame' | 'image' | 'card' | 'text';

/**
 * How fetched artifact BYTES should be rendered inline when the version has no
 * usable `spec`. Finer-grained than {@link PreviewMode}: it distinguishes the
 * markup family (html vs svg) and the text family (markdown vs plain) so the
 * renderer can pick the sandboxed iframe, a blob-URL `<img>`, the markdown
 * renderer, or an escaped `<pre>`. `card` means "not previewable inline".
 */
export type BytesPreviewMode =
  | 'iframe-html'
  | 'iframe-svg'
  | 'image'
  | 'text-markdown'
  | 'text-plain'
  | 'card';

/** Upper bound on fetched text rendered inline; larger bytes fall back to the card. */
export const MAX_INLINE_TEXT_BYTES = 512 * 1024;

const TEXT_PLAIN_MIME = new Set([
  'text/plain',
  'text/csv',
  'application/json',
  'text/xml',
  'application/xml',
]);

/**
 * Decide how to render downloadable artifact bytes from the version's
 * `mime_type` (falling back to `kind` when the mime is missing/coarse). Office
 * documents, pdf, and anything unrecognized map to `card` (download only).
 * Mermaid is intentionally NOT handled here — mermaid lives in `spec`, not as
 * stored bytes, so it stays on the spec-based frame path.
 */
export function bytesPreviewModeForMime(
  mimeType?: string | null,
  kind?: string | null,
): BytesPreviewMode {
  const mime = (mimeType ?? '').toLowerCase().split(';')[0].trim();
  const k = (kind ?? '').toLowerCase();

  if (mime === 'image/svg+xml') return 'iframe-svg';
  if (mime === 'text/html') return 'iframe-html';
  if (mime === 'text/markdown' || mime === 'text/x-markdown')
    return 'text-markdown';
  if (mime.startsWith('image/')) return 'image';
  if (TEXT_PLAIN_MIME.has(mime)) return 'text-plain';
  if (mime.startsWith('text/')) return 'text-plain';

  // Mime missing or coarse (e.g. application/octet-stream): fall back to kind.
  if (!mime || mime === 'application/octet-stream') {
    if (k === 'svg') return 'iframe-svg';
    if (k === 'html') return 'iframe-html';
    if (k === 'image') return 'image';
    if (k === 'code' || k === 'data') return 'text-plain';
  }

  return 'card';
}

/**
 * Discriminates the legacy notes/todo response (`artifact_type`) from the
 * generalized document/file response (`kind`).
 */
export function isDocumentArtifact(value: unknown): value is DocumentArtifact {
  if (!value || typeof value !== 'object') return false;
  const rec = value as Record<string, unknown>;
  return (
    typeof rec.kind === 'string' &&
    typeof rec.id === 'string' &&
    Array.isArray(rec.versions)
  );
}

const FRAME_KINDS = new Set(['html', 'svg', 'mermaid']);
const CARD_KINDS = new Set([
  'document',
  'spreadsheet',
  'presentation',
  'pdf',
  'file',
]);
const TEXT_KINDS = new Set(['code', 'data']);

/**
 * Map a `kind` (with optional mime fallback) to a preview mode. SVG/PDF/image
 * are also inferred from the mime type when the coarse `kind` is `html`/`file`,
 * so a server that only emits the canonical kind set still previews correctly.
 */
export function previewModeForKind(
  kind: string | null | undefined,
  mimeType?: string | null,
): PreviewMode {
  const mime = (mimeType ?? '').toLowerCase();

  if (mime.startsWith('image/svg')) return 'frame';
  if (mime === 'application/pdf') return 'card';
  if (mime.startsWith('image/')) return 'image';

  const k = (kind ?? '').toLowerCase();
  if (FRAME_KINDS.has(k)) return 'frame';
  if (k === 'image') return 'image';
  if (CARD_KINDS.has(k)) return 'card';
  if (TEXT_KINDS.has(k)) return 'text';
  return 'text';
}

/** Versions sorted newest-first by version number (does not mutate input). */
export function sortVersionsDesc(
  versions: ArtifactVersion[],
): ArtifactVersion[] {
  return [...versions].sort((a, b) => b.version - a.version);
}

/** The version row matching `current_version`, or the highest if absent. */
export function findCurrentVersion(
  artifact: Pick<DocumentArtifact, 'current_version' | 'versions'>,
): ArtifactVersion | null {
  if (!artifact.versions.length) return null;
  const match = artifact.versions.find(
    (v) => v.version === artifact.current_version,
  );
  if (match) return match;
  return sortVersionsDesc(artifact.versions)[0] ?? null;
}

/** Human-readable byte size (e.g. 1536 -> "1.5 KB"). */
export function formatBytes(size: number | null | undefined): string {
  if (size == null || Number.isNaN(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = size / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unit]}`;
}

/** Best display filename for a version, falling back to the artifact title/id. */
export function displayFilename(
  artifact: Pick<DocumentArtifact, 'id' | 'title'>,
  version: Pick<ArtifactVersion, 'filename'> | null,
): string {
  return version?.filename || artifact.title || `artifact-${artifact.id}`;
}

/**
 * Restrictive CSP for the preview iframe. No network, no scripts from origins,
 * no plugins; inline styles/SVG allowed so generated markup renders. Used for
 * html/svg markup that is embedded inline as static nodes.
 */
export const PREVIEW_CSP =
  "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; " +
  "font-src data:; script-src 'none'; form-action 'none'; base-uri 'none'; " +
  "frame-ancestors 'none'";

/**
 * CSP for the mermaid preview. Mermaid's `securityLevel: 'sandbox'` output is an
 * `<iframe src="data:text/html;base64,…" sandbox>` carrying the diagram, so the
 * preview document must additionally permit a `data:` nested frame. The diagram
 * itself runs inside that inner sandboxed frame; this outer document still
 * forbids scripts and origins.
 */
export const PREVIEW_CSP_MERMAID =
  "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; " +
  "font-src data:; script-src 'none'; frame-src data:; form-action 'none'; " +
  "base-uri 'none'; frame-ancestors 'none'";

/**
 * Wrap artifact markup in a minimal HTML document carrying the restrictive CSP.
 * The result is fed to a `sandbox="allow-scripts"`-less iframe via `srcdoc`;
 * the iframe must NOT be granted `allow-same-origin`, so the content cannot
 * reach the app's origin, cookies, or storage even though the CSP also blocks
 * script execution as defense in depth. The `mermaid` kind selects the variant
 * CSP that allows mermaid's inner `data:` sandboxed-iframe output to load.
 */
export function buildPreviewDocument(kind: string, content: string): string {
  const csp = kind === 'mermaid' ? PREVIEW_CSP_MERMAID : PREVIEW_CSP;
  return [
    '<!doctype html>',
    '<html>',
    '<head>',
    '<meta charset="utf-8">',
    `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
    '<style>html,body{margin:0;padding:12px;background:#fff;color:#111;' +
      'font-family:system-ui,sans-serif}img,svg{max-width:100%;height:auto}' +
      'iframe{border:0;width:100%}</style>',
    '</head>',
    '<body>',
    content,
    '</body>',
    '</html>',
  ].join('');
}

/**
 * Extract a filename from a `Content-Disposition` header, honoring both the
 * RFC 5987 `filename*` form and the plain quoted `filename` form.
 */
export function filenameFromContentDisposition(
  header: string | null,
): string | null {
  if (!header) return null;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].replace(/^"|"$/g, '').trim());
    } catch {
      return star[1].replace(/^"|"$/g, '').trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() ?? null;
}

/**
 * Turn a fetched download Response into a browser file-save, honoring
 * `Content-Disposition` when present. Returns false if the response is not OK.
 */
export async function triggerResponseDownload(
  response: Response,
  fallbackName: string,
): Promise<boolean> {
  if (!response.ok) return false;
  const name =
    filenameFromContentDisposition(
      response.headers.get('Content-Disposition'),
    ) || fallbackName;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } finally {
    URL.revokeObjectURL(url);
  }
  return true;
}
