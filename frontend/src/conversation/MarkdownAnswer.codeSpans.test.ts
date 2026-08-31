/**
 * Code must survive the markdown string pre-passes.
 *
 * ``processMarkdownContent`` rewrote every ``[N]`` as ``[N](#cite-N)`` and
 * ``preprocessLaTeX`` every ``\[…\]`` as ``$$…$$``, neither with any awareness
 * of code, so an index subscript or a bash prompt escape came out corrupted in
 * the rendered answer — and in what the copy button copied.
 *
 * Neither rewrite can move into a remark plugin, where a ``code`` node would be
 * distinct from a ``text`` one: remark-math tokenises ``$``/``$$`` while
 * parsing, so the LaTeX pass has to happen on the raw string. Hence the shared
 * ``applyOutsideCode`` masking helper rather than an AST visitor.
 */
import { describe, expect, it } from 'vitest';

import {
  applyOutsideCode,
  preprocessLaTeX,
  processMarkdownContent,
} from './MarkdownAnswer';

/** The rendered text of a single-segment answer. */
const text = (source: string) => processMarkdownContent(source)[0].content;

describe('citation rewriting spares code', () => {
  it('leaves an index subscript alone inside a fence', () => {
    const source = '```python\nfor row in cur:\n    print(row[0])\n```';
    expect(text(source)).toBe(source);
  });

  it('leaves an index subscript alone inside an inline span', () => {
    expect(text('Use `items[2]` here.')).toBe('Use `items[2]` here.');
  });

  it('leaves a mid-sentence triple-backtick span alone', () => {
    expect(text('inline ```code[0]``` end')).toBe('inline ```code[0]``` end');
  });

  it('leaves a triple-backtick span that starts a line alone', () => {
    // A backtick fence's info string cannot contain backticks, so this opens a
    // code span, not an unclosed fence that swallows the rest of the answer.
    expect(text('```code[0]``` and see [1]')).toBe(
      '```code[0]``` and see [1](#cite-1)',
    );
  });

  it('closes an inline span only on a run of its own length', () => {
    // The `` run does not close the ` span, so `b[1]` is still code.
    const source = 'Use `a`` b[1] more` end';
    expect(text(source)).toBe(source);
  });

  it('recognises a fence closed on a CRLF line', () => {
    expect(text('```js\r\nconst a = arr[0];\r\n```\r\nSee [1].')).toBe(
      '```js\r\nconst a = arr[0];\r\n```\r\nSee [1](#cite-1).',
    );
  });

  it('does not carry an inline span across a blank line', () => {
    // The blank line ends the paragraph, so the backticks never pair and
    // `bar[1]` is prose — which is how remark parses it too.
    expect(text('a `foo\n\nbar[1]` end')).toBe(
      'a `foo\n\nbar[1](#cite-1)` end',
    );
  });

  it('leaves an inline span that wraps a line alone', () => {
    expect(text('use `arr[0]\nnext` here')).toBe('use `arr[0]\nnext` here');
  });

  it('leaves a tilde fence alone', () => {
    const source = '~~~python\nprint(row[0])\n~~~';
    expect(text(source)).toBe(source);
  });

  it('leaves a fence nested in a longer one alone', () => {
    // A ``` run does not close a ```` fence, so the inner block is content.
    const source = '````markdown\n```js\nconst a = arr[0];\n```\n````';
    expect(text(source)).toBe(source);
  });

  it('leaves a fence indented under a list item alone', () => {
    const source =
      '1. Step:\n\n   ```js\n   const a = arr[0];\n\n   const b = arr[1];\n   ```';
    expect(text(source)).toBe(source);
  });

  it('leaves an unterminated fence alone while the answer is still streaming', () => {
    const source = '```python\nprint(row[0]';
    expect(text(source)).toBe(source);
  });

  it('leaves an unterminated inline span alone while streaming', () => {
    expect(text('Use `items[2')).toBe('Use `items[2');
  });

  it('leaves mermaid node labels alone', () => {
    // The cite pass runs before the ```mermaid split, so diagram source was
    // corrupted too and the render failed.
    const source = '```mermaid\nflowchart TD\n  A[0] --> B[1]\n```';
    expect(processMarkdownContent(source)[0].content).toBe(
      'flowchart TD\n  A[0] --> B[1]',
    );
  });

  it('still links a real citation in prose', () => {
    expect(text('See source [1] for details.')).toBe(
      'See source [1](#cite-1) for details.',
    );
  });

  it('links prose citations on either side of a fence without touching it', () => {
    expect(
      text('Per [1], run:\n```js\nconst a = arr[0];\n```\nthen [2].'),
    ).toBe(
      'Per [1](#cite-1), run:\n```js\nconst a = arr[0];\n```\nthen [2](#cite-2).',
    );
  });

  it('still links a citation on an indented list continuation line', () => {
    // Four-space indents are list content far more often than they are code,
    // so they are prose to the masker.
    expect(text('- one\n    - nested [1]')).toBe(
      '- one\n    - nested [1](#cite-1)',
    );
  });

  it('leaves an already-linked reference alone', () => {
    expect(text('see [1](#cite-1) ok')).toBe('see [1](#cite-1) ok');
  });
});

describe('LaTeX preprocessing spares code', () => {
  it('leaves bash prompt escapes alone', () => {
    // `\[`/`\]` are non-printing-sequence markers in PS1; the block rule turned
    // them into `$$` delimiters and broke the prompt.
    const source = '```bash\nPS1="\\[\\e[0m\\]$ "\n```';
    expect(preprocessLaTeX(source)).toBe(source);
  });

  it('leaves bracket character classes alone in an inline span', () => {
    expect(preprocessLaTeX('match `\\[0-9\\]` here')).toBe(
      'match `\\[0-9\\]` here',
    );
  });

  it('still converts real inline math in prose', () => {
    expect(preprocessLaTeX('The value \\(x^2\\) is fine.')).toBe(
      'The value $x^2$ is fine.',
    );
  });

  it('still converts real block math in prose', () => {
    expect(preprocessLaTeX('Given \\[a+b\\] we get')).toBe(
      'Given $$a+b$$ we get',
    );
  });

  it('does not link a subscript inside the math it just produced', () => {
    // `$a[1](#cite-1)$` is not something KaTeX can render.
    expect(text('value \\(a[1]\\) end')).toBe('value $a[1]$ end');
    expect(text('given \\[a[1]+b\\] we get [2]')).toBe(
      'given $$a[1]+b$$ we get [2](#cite-2)',
    );
  });
});

describe('applyOutsideCode', () => {
  const shout = (segment: string) => segment.toUpperCase();

  it('transforms prose either side of every code span', () => {
    expect(applyOutsideCode('a `b` c ```d``` e', shout)).toBe(
      'A `b` C ```d``` E',
    );
  });

  it('handles several inline spans on one line', () => {
    expect(applyOutsideCode('x `a` y `b` z', shout)).toBe('X `a` Y `b` Z');
  });

  it('treats a double-backtick span containing a backtick as one span', () => {
    expect(applyOutsideCode('x ``a`b`` y', shout)).toBe('X ``a`b`` Y');
  });

  it('does not close a long fence on a shorter run', () => {
    expect(applyOutsideCode('````\na\n```\nb\n````\nc', shout)).toBe(
      '````\na\n```\nb\n````\nC',
    );
  });

  it('passes an empty string through', () => {
    expect(applyOutsideCode('', shout)).toBe('');
  });
});
