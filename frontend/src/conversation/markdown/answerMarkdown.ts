/**
 * The string-level steps of rendering an answer, around the markdown parser.
 *
 * Math, code and citations are told apart by the parser (see `texMath.ts`,
 * `singleDollarMath.ts` and the remark plugins beside them). What is left
 * here works on the raw string only where the parser cannot help:
 *
 * - `normalizeMathFences` moves formula text off a ``$$`` fence line, which
 *   remark-math would read as the fence's metadata;
 * - `healStreamingMarkdown` closes what a half-streamed answer has left open;
 * - `splitAnswerBlocks` cuts the answer into its top-level blocks, so a
 *   streaming answer re-renders only the block that is still growing.
 */
import type { Root, RootContent } from 'mdast';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkParse from 'remark-parse';
import remend from 'remend';
import { type PluggableList, unified } from 'unified';

import { remarkSingleDollarMath } from './singleDollarMath';
import { remarkTexMath } from './texMath';

/** Syntax plugins; every parse of an answer, split or render, uses them. */
export const answerSyntaxPlugins: PluggableList = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
  remarkTexMath,
  remarkSingleDollarMath,
];

// A line's container prefix (blockquote markers, indentation) and the rest.
const LINE = /^((?:[ \t]*>)*[ \t]*)([\s\S]*)$/;
const FENCE_OPEN = /^(`{3,}|~{3,})/;
const DOLLAR_FENCE = /^\$\$\s*$/;

function splitLine(line: string): [prefix: string, rest: string] {
  const [, prefix, rest] = LINE.exec(line) ?? ['', '', line];
  return [prefix, rest];
}

function closesFence(rest: string, fence: string): boolean {
  const run = rest.trim();
  return (
    run.length >= fence.length && run[0] === fence[0] && /^(?:`+|~+)$/.test(run)
  );
}

/**
 * Puts a ``$$`` fence's formula on its own line: ``$$\begin{aligned}`` opens a
 * block whose first line remark-math reads as metadata and drops, and a
 * closing ``\end{aligned}$$`` never closes it, so the block ran to the end of
 * the answer. Code fences are left alone.
 */
export function normalizeMathFences(content: string): string {
  if (!content.includes('$$')) return content;
  const out: string[] = [];
  let fence: string | null = null;
  let inMath = false;

  for (const line of content.split('\n')) {
    const [prefix, rest] = splitLine(line);
    if (fence) {
      if (closesFence(rest, fence)) fence = null;
      out.push(line);
      continue;
    }
    if (inMath) {
      const closing = /^(.*\S)[ \t]*\$\$\s*$/.exec(rest);
      if (DOLLAR_FENCE.test(rest)) {
        inMath = false;
      } else if (closing) {
        out.push(prefix + closing[1], `${prefix}$$`);
        inMath = false;
        continue;
      }
      out.push(line);
      continue;
    }
    const codeFence = FENCE_OPEN.exec(rest);
    const opening = /^\$\$(?!\$)(.*\S)\s*$/.exec(rest);
    if (codeFence) {
      fence = codeFence[1];
    } else if (DOLLAR_FENCE.test(rest)) {
      inMath = true;
    } else if (opening && !opening[1].includes('$$')) {
      out.push(`${prefix}$$`, prefix + opening[1].trimStart());
      inMath = true;
      continue;
    }
    out.push(line);
  }
  return out.join('\n');
}

// Inline code in a stretch of prose, open spans included, so a `$$` in it is
// not counted as math.
const INLINE_CODE = /(`+)[\s\S]*?(?:\1|$)/g;

// Splits a half-streamed answer at the math it is in the middle of writing:
// `head` is everything before that formula, `math` the formula closed. A ``$$``
// or line-start ``\[`` block gets its closing fence, an inline ``$$`` its
// closing ``$$``, and one with nothing after it yet is held back. Inside a code
// fence nothing is touched: a shell's `$$` is not math.
function splitOpenMath(content: string): { head: string; math: string } {
  let fence: string | null = null;
  let block: { close: string; prefix: string; start: number } | null = null;
  let offset = 0;

  for (const line of content.split('\n')) {
    const [prefix, rest] = splitLine(line);
    if (fence) {
      if (closesFence(rest, fence)) fence = null;
    } else if (block) {
      const closed =
        block.close === '$$' ? DOLLAR_FENCE.test(rest) : /\\\]\s*$/.test(rest);
      if (closed) block = null;
    } else if (FENCE_OPEN.test(rest)) {
      fence = FENCE_OPEN.exec(rest)![1];
    } else if (DOLLAR_FENCE.test(rest)) {
      block = { close: '$$', prefix, start: offset };
    } else if (rest.startsWith('\\[') && !rest.includes('\\]')) {
      block = { close: '\\]', prefix, start: offset };
    }
    offset += line.length + 1;
  }
  if (fence) return { head: content, math: '' };
  if (block) {
    return {
      head: content.slice(0, block.start),
      math: `${content.slice(block.start)}\n${block.prefix}${block.close}`,
    };
  }

  const paragraphStart = content.lastIndexOf('\n\n') + 1;
  const prose = content
    .slice(paragraphStart)
    .replace(INLINE_CODE, '')
    .replace(/\\\$/g, '');
  const dollars = prose.match(/\$\$/g)?.length ?? 0;
  if (dollars % 2 === 0) return { head: content, math: '' };
  const opener = content.lastIndexOf('$$');
  const formula = content.slice(opener);
  return {
    head: content.slice(0, opener),
    math: formula.slice(2).trim() ? `${formula}$$` : '',
  };
}

const REMEND_OPTIONS = {
  // Math is closed above, code-aware; remend's own pass appends `$$` inside
  // an open code fence.
  katex: false,
  inlineKatex: false,
  // A half-typed `[1` or `\[` is not a link, and remend would strip its `[`.
  links: false,
  images: false,
  // These two rewrite text that is already complete, so the answer would
  // change once it stops streaming.
  comparisonOperators: false,
  singleTilde: false,
};

/**
 * Closes what a half-streamed answer leaves open (``**bold``, `` `code``,
 * ``$$`` and ``\[`` math), so it renders as it will once complete instead of
 * flashing raw markdown. Only ever applied while the answer streams.
 */
export function healStreamingMarkdown(content: string): string {
  // Emphasis is closed before the open formula, never after it: appended to
  // the closing fence (``$$**``), it would stop the fence from closing.
  const { head, math } = splitOpenMath(content);
  if (!math) return remend(head, REMEND_OPTIONS);
  const lineBreak = head.match(/\n*$/)![0];
  return (
    remend(head.slice(0, head.length - lineBreak.length), REMEND_OPTIONS) +
    lineBreak +
    math
  );
}

export type AnswerBlock =
  { type: 'markdown'; content: string } | { type: 'mermaid'; content: string };

const parser = unified().use(remarkParse).use(answerSyntaxPlugins);

// Where a block's first line starts, so an indented block keeps its indent.
function lineStart(content: string, offset: number): number {
  const start = content.lastIndexOf('\n', offset - 1) + 1;
  return /^[ \t]*$/.test(content.slice(start, offset)) ? start : offset;
}

// A mermaid fence is drawn once it is closed; until then it streams as code.
function isDiagram(node: RootContent, source: string): boolean {
  if (node.type !== 'code' || node.lang !== 'mermaid') return false;
  const lines = source.trimEnd().split('\n');
  const opening = FENCE_OPEN.exec(lines[0].trim());
  return (
    lines.length > 1 &&
    opening !== null &&
    closesFence(lines[lines.length - 1], opening[1])
  );
}

/**
 * Cuts an answer into its top-level blocks, each rendered on its own, and its
 * closed mermaid fences, drawn as diagrams. An answer with link or footnote
 * definitions stays whole between diagrams, since a reference resolves only
 * against definitions in the same parse.
 */
export function splitAnswerBlocks(content: string): AnswerBlock[] {
  const tree: Root = parser.parse(content);
  const keepWhole = tree.children.some(
    (node) => node.type === 'definition' || node.type === 'footnoteDefinition',
  );
  const blocks: AnswerBlock[] = [];
  let groupStart: number | null = null;

  for (const node of tree.children) {
    const start = lineStart(content, node.position?.start.offset ?? 0);
    const end = node.position?.end.offset ?? content.length;
    if (node.type === 'code' && isDiagram(node, content.slice(start, end))) {
      if (groupStart !== null) {
        blocks.push({
          type: 'markdown',
          content: content.slice(groupStart, start),
        });
        groupStart = null;
      }
      blocks.push({ type: 'mermaid', content: node.value.trim() });
    } else if (keepWhole) {
      groupStart ??= start;
    } else {
      blocks.push({ type: 'markdown', content: content.slice(start, end) });
    }
  }
  if (groupStart !== null) {
    blocks.push({ type: 'markdown', content: content.slice(groupStart) });
  }
  return blocks;
}
