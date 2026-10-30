/**
 * The docs-gap report as a CSV file, built from the rows on screen. Prompts
 * are user text, so a cell that a spreadsheet would read as a formula is
 * defused with a leading apostrophe.
 */
import { downloadBlob } from '../utils/browserUtils';
import type { DocsGapRow, DocsGapsGroup } from './types';

export const DOCS_GAPS_CSV_HEADER = [
  'group',
  'key',
  'name',
  'source',
  'gaps',
  'gaps_low',
  'gaps_high',
  'questions',
  'share',
  'share_low',
  'share_high',
  'previous_gaps',
  'example_questions',
];

/** Tells Excel the file is UTF-8. */
const BOM = '\uFEFF';

/** Characters a spreadsheet starts a formula (or a DDE call) with. */
const FORMULA_START = /^[=+\-@\t\r]/;

/** One CSV cell: formula-guarded, then quoted as RFC 4180 asks. */
export function csvCell(value: string | number): string {
  let text = typeof value === 'number' ? String(value) : value;
  if (FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** A number as data: unformatted, without float noise (0.30000000000000004). */
const plain = (value: number): number =>
  Number.isFinite(value) ? Math.round(value * 10_000) / 10_000 : 0;

/**
 * The rows as CSV: English machine keys in the header, numbers unformatted,
 * CRLF line ends and a UTF-8 BOM, so Excel reads non-Latin text right.
 */
export function docsGapsCsv(
  rows: DocsGapRow[],
  groupBy: DocsGapsGroup,
): string {
  const lines = [
    DOCS_GAPS_CSV_HEADER,
    ...rows.map((row) => [
      groupBy,
      row.key ?? '',
      row.name ?? '',
      row.source ?? '',
      plain(row.expected_gaps),
      plain(row.low * row.turns),
      plain(row.high * row.turns),
      row.turns,
      plain(row.rate),
      plain(row.low),
      plain(row.high),
      plain(row.previous_expected),
      row.examples.map((example) => example.prompt).join(' | '),
    ]),
  ];
  const body = lines.map((cells) => cells.map(csvCell).join(',')).join('\r\n');
  return `${BOM}${body}\r\n`;
}

/**
 * `docs-gaps-<agent|all>-<group>-<window>-<YYYY-MM-DD>.csv`, the agent's name
 * reduced to letters, digits and dashes.
 */
export function docsGapsFileName({
  agentName,
  groupBy,
  filterOption,
  date = new Date(),
}: {
  agentName?: string;
  groupBy: DocsGapsGroup;
  filterOption: string;
  date?: Date;
}): string {
  const slug = agentName
    ? agentName
        .toLocaleLowerCase()
        .replace(/[^\p{L}\p{N}]+/gu, '-')
        .replace(/^-+|-+$/g, '') || 'agent'
    : 'all';
  const day = [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
  return `docs-gaps-${slug}-${groupBy}-${filterOption}-${day}.csv`;
}

/** Hands the text to the browser as a file download. */
export function downloadCsv(text: string, fileName: string): void {
  downloadBlob(new Blob([text], { type: 'text/csv;charset=utf-8' }), fileName);
}
