import { deriveArtifactChips } from './artifactChips';
import type { ToolCallsType } from './types';

/**
 * What an artifact is, for its card's icon and label. A file's kind comes
 * from its extension (or mime type); a note, todo or memory has no file, so
 * the tool that made it says which.
 */
export type ArtifactKind =
  | 'page'
  | 'pdf'
  | 'slides'
  | 'document'
  | 'spreadsheet'
  | 'data'
  | 'image'
  | 'note'
  | 'todo'
  | 'memory'
  | 'file';

/** One artifact as an answer shows it: a card that opens it in the side panel. */
export type ArtifactCardItem = {
  id: string;
  /** The artifact's title, else its filename. */
  title: string;
  kind: ArtifactKind;
  /** The version the card points at; unset for a note or todo. */
  version?: number;
  /** The download name. */
  filename?: string;
  /** The tool that made it ('' for a workflow run's file); the panel loads a note or todo by it. */
  toolName: string;
  /** A file you can save; a note or todo is read in the panel only. */
  downloadable: boolean;
};

/** What opening an artifact asks the side panel for; `version` is the one its card names. */
export type OpenArtifactRequest = {
  id: string;
  toolName: string;
  version?: number;
};

/** A workflow run's artifact as `GET /api/artifacts?workflow_run_id=` lists it. */
export type RunArtifactSummary = {
  id: string;
  kind: string | null;
  title: string | null;
  current_version: number | null;
  filename?: string | null;
  mime_type?: string | null;
};

const KIND_BY_EXTENSION: Record<string, ArtifactKind> = {
  html: 'page',
  htm: 'page',
  pdf: 'pdf',
  pptx: 'slides',
  ppt: 'slides',
  odp: 'slides',
  key: 'slides',
  docx: 'document',
  doc: 'document',
  odt: 'document',
  rtf: 'document',
  md: 'document',
  txt: 'document',
  xlsx: 'spreadsheet',
  xls: 'spreadsheet',
  ods: 'spreadsheet',
  csv: 'data',
  tsv: 'data',
  json: 'data',
  xml: 'data',
  parquet: 'data',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  svg: 'image',
  webp: 'image',
};

// Checked in order: the first matching mime fragment wins.
const KIND_BY_MIME: [string, ArtifactKind][] = [
  ['text/html', 'page'],
  ['application/pdf', 'pdf'],
  ['presentation', 'slides'],
  ['wordprocessing', 'document'],
  ['msword', 'document'],
  ['spreadsheet', 'spreadsheet'],
  ['ms-excel', 'spreadsheet'],
  ['text/csv', 'data'],
  ['application/json', 'data'],
  ['image/', 'image'],
  ['text/markdown', 'document'],
  ['text/plain', 'document'],
];

/**
 * The kind of an artifact, from its file or, for a note or todo, its tool.
 *
 * Args:
 *   filename: The file's name, when it is a file.
 *   mimeType: The file's mime type, used when the name says nothing.
 *   toolName: The tool that made it.
 *
 * Returns:
 *   The card's kind; `file` when nothing is known.
 */
export function artifactKind({
  filename,
  mimeType,
  toolName,
}: {
  filename?: string | null;
  mimeType?: string | null;
  toolName?: string | null;
}): ArtifactKind {
  const extension = filename?.includes('.')
    ? filename.split('.').pop()?.toLowerCase()
    : undefined;
  // Own keys only: a generated file named `x.constructor` must not read
  // Object.prototype.
  if (
    extension &&
    Object.prototype.hasOwnProperty.call(KIND_BY_EXTENSION, extension)
  )
    return KIND_BY_EXTENSION[extension];
  const mime = (mimeType ?? '').toLowerCase();
  for (const [fragment, kind] of KIND_BY_MIME) {
    if (mime.includes(fragment)) return kind;
  }
  if (!filename && !mime) {
    const tool = (toolName ?? '').toLowerCase();
    if (tool.includes('todo')) return 'todo';
    if (tool.includes('memory')) return 'memory';
    if (tool.includes('note')) return 'note';
  }
  return 'file';
}

/** One card per artifact a turn's completed tool calls produced. */
export function cardsFromToolCalls(
  toolCalls: ToolCallsType[] | undefined,
): ArtifactCardItem[] {
  return deriveArtifactChips(toolCalls).map((chip) => ({
    id: chip.id,
    title: chip.title || chip.filename || chip.label,
    kind: artifactKind({ filename: chip.filename, toolName: chip.toolName }),
    version: chip.version,
    filename: chip.filename,
    toolName: chip.toolName,
    // A file artifact reports its filename; a note or todo only an id.
    downloadable: Boolean(chip.filename),
  }));
}

/**
 * One card per artifact a workflow run produced.
 *
 * Args:
 *   artifacts: The run's list entries.
 *   untitled: Names an artifact with neither a title nor a file, from its
 *     short id.
 */
export function cardsFromRunArtifacts(
  artifacts: RunArtifactSummary[],
  untitled: (shortId: string) => string = (shortId) => shortId,
): ArtifactCardItem[] {
  return artifacts.map((artifact) => ({
    id: artifact.id,
    title:
      artifact.title || artifact.filename || untitled(artifact.id.slice(0, 8)),
    kind: artifactKind({
      filename: artifact.filename,
      mimeType: artifact.mime_type,
    }),
    version: artifact.current_version ?? undefined,
    filename: artifact.filename ?? undefined,
    toolName: '',
    // No filename means the current version's row is missing: nothing to save.
    downloadable: Boolean(artifact.filename),
  }));
}

// Deliverables first, then the images behind them, then raw data and the rest.
const KIND_RANK: Record<ArtifactKind, number> = {
  page: 0,
  pdf: 0,
  slides: 0,
  document: 0,
  spreadsheet: 0,
  note: 0,
  todo: 0,
  memory: 0,
  image: 1,
  data: 2,
  file: 3,
};

/**
 * An answer's cards in the order it shows them: documents, then images, then
 * data and other files, each group in the order produced, one card per id.
 */
export function orderArtifactCards(
  items: ArtifactCardItem[],
): ArtifactCardItem[] {
  const seen = new Set<string>();
  const unique = items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
  return unique
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        KIND_RANK[a.item.kind] - KIND_RANK[b.item.kind] || a.index - b.index,
    )
    .map(({ item }) => item);
}
