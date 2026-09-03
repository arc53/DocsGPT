export const AUDIO_FILE_ACCEPT: Record<string, string[]> = {
  'audio/mpeg': ['.mp3'],
  'audio/mp4': ['.m4a'],
  'audio/ogg': ['.ogg'],
  'audio/wav': ['.wav'],
  'audio/webm': ['.webm'],
  'video/webm': ['.webm'],
};

export const FILE_UPLOAD_ACCEPT: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'text/x-rst': ['.rst'],
  'text/x-markdown': ['.md'],
  'application/zip': ['.zip'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': [
    '.docx',
  ],
  'application/json': ['.json'],
  'text/csv': ['.csv'],
  'text/html': ['.html'],
  'application/epub+zip': ['.epub'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': [
    '.xlsx',
  ],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': [
    '.pptx',
  ],
  'image/png': ['.png'],
  'image/jpeg': ['.jpeg'],
  'image/jpg': ['.jpg'],
  ...AUDIO_FILE_ACCEPT,
};

export const FILE_UPLOAD_ACCEPT_ATTR = [
  '.pdf',
  '.txt',
  '.rst',
  '.md',
  '.zip',
  '.docx',
  '.json',
  '.csv',
  '.html',
  '.epub',
  '.xlsx',
  '.pptx',
  '.png',
  '.jpeg',
  '.jpg',
  '.wav',
  '.mp3',
  '.m4a',
  '.ogg',
  '.webm',
].join(',');

export const AUDIO_FILE_ACCEPT_ATTR = [
  '.wav',
  '.mp3',
  '.m4a',
  '.ogg',
  '.webm',
].join(',');

export const SOURCE_FILE_TREE_ACCEPT_ATTR = [
  '.rst',
  '.md',
  '.pdf',
  '.txt',
  '.docx',
  '.csv',
  '.epub',
  '.html',
  '.mdx',
  '.json',
  '.xlsx',
  '.pptx',
  '.png',
  '.jpg',
  '.jpeg',
].join(',');

/**
 * Chat-attachment suffixes with a dedicated parser. Mirrors the backend's
 * `ATTACHMENT_PARSER_EXTENSIONS` (application/parser/file/constants.py) —
 * update both together. Zip is absent: source ingestion extracts archives,
 * the attachment path does not.
 *
 * Not the whole allow-list, and `.txt` is deliberately not here: a suffix
 * that isn't listed (.txt, .py, .log, .yaml) is read by the backend's
 * plain-text fallthrough, so it is judged on content by
 * `partitionAttachmentFiles` instead, exactly as the server does.
 */
export const ATTACHMENT_PARSER_EXTENSIONS: readonly string[] = [
  '.rst',
  '.md',
  '.mdx',
  '.pdf',
  '.docx',
  '.csv',
  '.epub',
  '.html',
  '.xhtml',
  '.json',
  '.xlsx',
  '.pptx',
  '.adoc',
  '.asciidoc',
  '.png',
  '.jpg',
  '.jpeg',
  '.tiff',
  '.tif',
  '.bmp',
  '.webp',
  '.vtt',
  '.xml',
  '.wav',
  '.mp3',
  '.m4a',
  '.ogg',
  '.webm',
];

/**
 * Picker filter for the Attach button. A hint only — pickers may ignore it,
 * and it must never be narrower than what the upload accepts: `text/*` (plus
 * `.txt` explicitly) keeps parserless text files such as .py and .log
 * selectable, since the gate reads those happily.
 */
export const ATTACHMENT_FILE_ACCEPT_ATTR = [
  ...ATTACHMENT_PARSER_EXTENSIONS,
  '.txt',
  'text/*',
].join(',');

/** Lower-cased last extension including the dot, or '' (dotfiles have none). */
export function getFileExtension(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? '';
  const dot = base.lastIndexOf('.');
  if (dot <= 0) return '';
  return base.slice(dot).toLowerCase();
}

/**
 * Whether the backend has a parser for this suffix. False is not a refusal:
 * the file then has to read as text. Never decided by the mime type the
 * picker reports — mobile pickers ignore `accept` and lie about types.
 */
export function hasAttachmentParser(file: { name: string }): boolean {
  const ext = getFileExtension(file.name);
  return ext !== '' && ATTACHMENT_PARSER_EXTENSIONS.includes(ext);
}

// Mirrors application/upload_limits.py: enough of the head to recognise a
// container header, and a tolerance that keeps real text (UTF-8 accents, an
// ANSI-coloured log) in while a random binary stays out.
const TEXT_SNIFF_BYTES = 8192;
const MAX_NONTEXT_RATIO = 0.1;
// Control bytes that occur in ordinary text: tab, LF, VT, FF, CR, ESC.
const TEXT_CONTROL_BYTES = new Set([0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1b]);
// A UTF-16/32 file is half NUL bytes, so it has to be recognised by its BOM
// before the NUL test — Notepad's "Unicode" .txt is ordinary text.
const TEXT_BOMS = [
  [0xef, 0xbb, 0xbf],
  [0xff, 0xfe],
  [0xfe, 0xff],
  [0x00, 0x00, 0xfe, 0xff],
];

/** Whether a leading byte sample reads as text rather than binary. */
export function looksLikeText(sample: Uint8Array): boolean {
  if (sample.length === 0) return true;
  if (TEXT_BOMS.some((bom) => bom.every((byte, i) => sample[i] === byte)))
    return true;
  let nontext = 0;
  for (const byte of sample) {
    if (byte === 0x00) return false;
    if ((byte < 0x20 && !TEXT_CONTROL_BYTES.has(byte)) || byte === 0x7f)
      nontext += 1;
  }
  return nontext / sample.length <= MAX_NONTEXT_RATIO;
}

async function isSupportedAttachmentFile(file: File): Promise<boolean> {
  if (hasAttachmentParser(file)) return true;
  try {
    const head = await file.slice(0, TEXT_SNIFF_BYTES).arrayBuffer();
    return looksLikeText(new Uint8Array(head));
  } catch {
    // Can't read it here — let the upload run and the server decide.
    return true;
  }
}

/**
 * Split a selection into what the backend can read and what it will refuse,
 * preserving order. Files with a parser pass on their suffix; the rest are
 * sniffed, so source, config and log files go through and a video does not.
 */
export async function partitionAttachmentFiles(files: File[]): Promise<{
  supported: File[];
  unsupported: File[];
}> {
  const verdicts = await Promise.all(files.map(isSupportedAttachmentFile));
  const supported: File[] = [];
  const unsupported: File[] = [];
  files.forEach((file, index) => {
    (verdicts[index] ? supported : unsupported).push(file);
  });
  return { supported, unsupported };
}

/** The ``message`` of a JSON error body, if the server sent one. */
export function parseUploadErrorMessage(body: string): string | undefined {
  if (!body) return undefined;
  try {
    const parsed = JSON.parse(body) as { message?: unknown };
    return typeof parsed?.message === 'string' && parsed.message
      ? parsed.message
      : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Per-file reasons from an error body, keyed by `upload_index`. A rejected
 * batch carries one `errors` entry per file, so each chip can say why it
 * failed instead of every chip repeating the first file's reason.
 */
export function parseUploadErrorsByIndex(body: string): Map<number, string> {
  const byIndex = new Map<number, string>();
  if (!body) return byIndex;
  try {
    const parsed = JSON.parse(body) as { errors?: unknown };
    if (!Array.isArray(parsed?.errors)) return byIndex;
    for (const entry of parsed.errors as {
      upload_index?: unknown;
      error?: unknown;
    }[]) {
      if (
        typeof entry?.upload_index === 'number' &&
        typeof entry.error === 'string'
      )
        byIndex.set(entry.upload_index, entry.error);
    }
  } catch {
    // Not JSON (a proxy's HTML 502, say) — the caller falls back.
  }
  return byIndex;
}
