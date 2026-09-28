/**
 * Decides display versus inline math on the syntax tree, where the parser has
 * already told math, code and prose apart.
 *
 * An inline formula becomes display math when
 * - it is written with a block delimiter (``$$`` or ``\[``) and sits on a line
 *   of its own: ``$$E=mc^2$$`` alone in a paragraph, or a ``\[ … \]`` line the
 *   flow construct did not take (a lazy line inside a quote, say); or
 * - KaTeX can only typeset it in display mode (``\tag``, or an environment such
 *   as ``align``); inline, it would be a red error instead of an equation.
 *
 * A promoted formula splits its paragraph: the text before and after stays a
 * paragraph of its own. Where no paragraph can be split (a table cell, a
 * heading) a display-only formula is still typeset in display mode, in place.
 */
import type { Paragraph, PhrasingContent, Root, RootContent } from 'mdast';
import { SKIP, visit } from 'unist-util-visit';

type InlineMath = Extract<PhrasingContent, { type: 'inlineMath' }>;

// `\tag` and the environments KaTeX refuses outside display mode.
const DISPLAY_ONLY =
  /\\tag\b|\\begin\{(?:equation|align|alignat|gather|split|CD)\*?\}/;

const displayClasses = ['language-math', 'math-display'];

function isInlineMath(node: PhrasingContent): node is InlineMath {
  return node.type === 'inlineMath';
}

function blockDelimited(node: InlineMath, source: string): boolean {
  const start = node.position?.start.offset;
  if (start === undefined) return false;
  const opener = source.slice(start, start + 2);
  return opener === '$$' || opener === '\\[';
}

// Whether the siblings either side of `index` end and start a line.
function aloneOnLine(children: PhrasingContent[], index: number): boolean {
  const before = children[index - 1];
  const after = children[index + 1];
  const endsLine =
    !before ||
    before.type === 'break' ||
    (before.type === 'text' && /(?:^|\n)[ \t]*$/.test(before.value));
  const startsLine =
    !after ||
    after.type === 'break' ||
    (after.type === 'text' && /^[ \t]*(?:\n|$)/.test(after.value));
  return endsLine && startsLine;
}

function toDisplay(node: InlineMath): RootContent {
  return {
    type: 'math',
    meta: null,
    value: node.value,
    position: node.position,
    data: {
      hName: 'pre',
      hChildren: [
        {
          type: 'element',
          tagName: 'code',
          properties: { className: displayClasses },
          children: [{ type: 'text', value: node.value }],
        },
      ],
    },
  };
}

// The paragraph around each promoted formula, cut at it, with the line breaks
// that separated them dropped.
function splitParagraph(
  paragraph: Paragraph,
  promote: (child: PhrasingContent, index: number) => boolean,
): RootContent[] {
  const blocks: RootContent[] = [];
  let run: PhrasingContent[] = [];
  let trimNext = false;

  const flush = () => {
    const last = run[run.length - 1];
    if (last?.type === 'break') run.pop();
    else if (last?.type === 'text') last.value = last.value.trimEnd();
    run = run.filter((child) => child.type !== 'text' || child.value !== '');
    if (run.length > 0) blocks.push({ type: 'paragraph', children: run });
    run = [];
  };

  paragraph.children.forEach((child, index) => {
    if (isInlineMath(child) && promote(child, index)) {
      flush();
      blocks.push(toDisplay(child));
      trimNext = true;
      return;
    }
    if (trimNext) {
      trimNext = false;
      if (child.type === 'break') return;
      if (child.type === 'text') child.value = child.value.trimStart();
    }
    run.push(child);
  });
  flush();
  return blocks;
}

export function remarkDisplayMath() {
  return (tree: Root, file: { value?: unknown }) => {
    const source = String(file.value);

    visit(tree, 'paragraph', (node, index, parent) => {
      if (!parent || index === undefined) return;
      const promote = (child: PhrasingContent, at: number) =>
        isInlineMath(child) &&
        (DISPLAY_ONLY.test(child.value) ||
          (blockDelimited(child, source) && aloneOnLine(node.children, at)));
      if (!node.children.some(promote)) return;
      const blocks = splitParagraph(node, promote);
      // A paragraph's parent (the root, a list item, a quote) holds blocks.
      (parent.children as RootContent[]).splice(index, 1, ...blocks);
      return [SKIP, index + blocks.length];
    });

    // Nowhere to split (a table cell, a heading, inside bold): typeset a
    // display-only formula in display mode where it stands.
    visit(tree, 'inlineMath', (node) => {
      if (!DISPLAY_ONLY.test(node.value)) return;
      node.data = { ...node.data, hProperties: { className: displayClasses } };
    });
  };
}
