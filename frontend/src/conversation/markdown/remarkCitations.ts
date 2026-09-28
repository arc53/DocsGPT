/**
 * Links source citations, ``[N]``, in the prose of an answer.
 *
 * Runs on the syntax tree, so only plain text is ever linked: code, inline
 * code and math are their own nodes, never `text`, and link text is skipped.
 * An index like `row[0]` in code, or `a[1]` in a formula, stays what it is.
 * A bare ``[1]`` with no matching definition is text to the parser; a
 * reference link ``[docs][1]`` with a ``[1]: url`` definition stays a link,
 * and brackets the answer escaped, ``arr\[1\]``, stay brackets.
 *
 * The link targets ``#cite-N``, which `MarkdownAnswer` renders as the "jump to
 * source" pill.
 */
import type { PhrasingContent, Root, Text } from 'mdast';
import { asciiPunctuation } from 'micromark-util-character';
import { SKIP, visit } from 'unist-util-visit';

export type CitationOptions = {
  /**
   * How many sources the answer has; only ``[1]`` to ``[sourceCount]`` are
   * linked, since any other number has no source to jump to. Unset links
   * every ``[N]``.
   */
  sourceCount?: number;
};

const CITATION = /\[(\d+)\]/g;

// The offsets in `node.value` of characters the source wrote as a backslash
// escape. The parser resolves escapes, so ``\[1\]`` and ``[1]`` are the same
// text; only the source tells them apart. Anything else that makes the value
// differ from the source (an entity, a quote marker) ends the walk, and the
// rest of the node counts as unescaped.
function escapedOffsets(node: Text, source: string): Set<number> {
  const escaped = new Set<number>();
  const start = node.position?.start.offset;
  const end = node.position?.end.offset;
  if (start === undefined || end === undefined) return escaped;
  const raw = source.slice(start, end);
  if (!raw.includes('\\')) return escaped;

  const { value } = node;
  let i = 0;
  for (let j = 0; j < value.length && i < raw.length; j++) {
    // Indentation the parser dropped from a continuation line.
    while (raw[i] !== value[j] && (raw[i] === ' ' || raw[i] === '\t')) i++;
    if (
      raw[i] === '\\' &&
      raw[i + 1] === value[j] &&
      asciiPunctuation(value.charCodeAt(j))
    ) {
      escaped.add(j);
      i += 2;
    } else if (raw[i] === value[j]) {
      i++;
    } else {
      break;
    }
  }
  return escaped;
}

export function remarkCitations({ sourceCount }: CitationOptions = {}) {
  const citable = (n: number) =>
    sourceCount === undefined || (n >= 1 && n <= sourceCount);

  return (tree: Root, file: { value?: unknown }) => {
    const source = String(file.value ?? '');

    visit(tree, (node, index, parent) => {
      if (node.type === 'link' || node.type === 'linkReference') return SKIP;
      if (node.type !== 'text' || !parent || index === undefined) return;

      const escaped = escapedOffsets(node, source);
      const parts: PhrasingContent[] = [];
      let last = 0;
      for (const match of node.value.matchAll(CITATION)) {
        if (!citable(Number(match[1])) || escaped.has(match.index)) continue;
        if (match.index > last) {
          parts.push({
            type: 'text',
            value: node.value.slice(last, match.index),
          });
        }
        parts.push({
          type: 'link',
          url: `#cite-${match[1]}`,
          children: [{ type: 'text', value: match[1] }],
        });
        last = match.index + match[0].length;
      }
      if (parts.length === 0) return;
      if (last < node.value.length) {
        parts.push({ type: 'text', value: node.value.slice(last) });
      }
      parent.children.splice(index, 1, ...parts);
      return [SKIP, index + parts.length];
    });
  };
}
