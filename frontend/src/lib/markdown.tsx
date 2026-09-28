import type { CSSProperties } from 'react';
import type { Components } from 'react-markdown';

import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

/**
 * Heading renderers shared by every markdown surface (chat answers, the wiki
 * view, note artifacts, document previews). Spread into `components`.
 */
export const markdownHeadings: Components = {
  h1: ({ children }) => (
    <h1 className="mt-4 mb-2 text-xl font-semibold">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-4 mb-2 text-lg font-semibold">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-3 mb-2 text-base font-semibold">{children}</h3>
  ),
};

/**
 * A GFM column's alignment (`:---:`, `---:`), which react-markdown hands a
 * cell as `style.textAlign`.
 *
 * @param style The cell's style prop.
 * @returns The `ui/table` align value, or undefined for the default.
 */
function cellAlign(
  style: CSSProperties | undefined,
): 'left' | 'right' | 'center' | undefined {
  const align = style?.textAlign;
  return align === 'left' || align === 'right' || align === 'center'
    ? align
    : undefined;
}

/**
 * Table renderers shared by every markdown surface (chat answers, wiki pages,
 * chunks, note artifacts, document previews): the `ui/table` parts, so a
 * markdown table looks like every other table in the app. The bordered frame
 * scrolls sideways, so a wide table never widens the column, and a narrow
 * one shrinks to fit (`min-w-0`). Spread into `components` after
 * `markdownHeadings`.
 */
export const markdownTables: Components = {
  table: ({ children }) => (
    <TableContainer>
      <Table minWidth="min-w-0">{children}</Table>
    </TableContainer>
  ),
  thead: ({ children }) => <TableHead>{children}</TableHead>,
  tbody: ({ children }) => <TableBody>{children}</TableBody>,
  tr: ({ children }) => <TableRow>{children}</TableRow>,
  th: ({ children, style }) => (
    <TableHeader align={cellAlign(style)}>{children}</TableHeader>
  ),
  td: ({ children, style }) => (
    <TableCell align={cellAlign(style)}>{children}</TableCell>
  ),
};
