/**
 * Code must survive citation linking and math parsing.
 *
 * Both used to be regex passes over the raw answer, and both corrupted the
 * user's own code: `print(row[0])` rendered as `print(row[0](#cite-0))`, and
 * `PS1="\[\e[0m\]"` as `PS1="$$\e[0m$$"`, in the answer and in what the copy
 * button copied. Math is now parsed by the markdown parser and citations are
 * linked on its syntax tree, where code is never plain text; these cases pin
 * that down on the rendered answer.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({ useDarkTheme: () => [false, vi.fn()] }));
vi.mock('../components/MermaidRenderer', () => ({
  default: ({ code }: { code: string }) => (
    <div data-testid="mermaid">{code}</div>
  ),
}));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

import MarkdownAnswer from './MarkdownAnswer';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(content: string, isStreaming = false) {
  act(() =>
    root.render(<MarkdownAnswer content={content} isStreaming={isStreaming} />),
  );
}

/** Text of every code block and inline code span, in order. */
function code() {
  return Array.from(container.querySelectorAll('code')).map(
    (node) => node.textContent,
  );
}

/** Citation pills, the only buttons these answers render. */
function citations() {
  return Array.from(container.querySelectorAll('button')).map(
    (node) => node.textContent,
  );
}

function math() {
  return container.querySelectorAll('.katex, .katex-error').length;
}

describe('citation linking spares code', () => {
  it('leaves an index subscript alone inside a fence', () => {
    render('```python\nfor row in cur:\n    print(row[0])\n```');
    expect(code()).toEqual(['for row in cur:\n    print(row[0])']);
    expect(citations()).toEqual([]);
  });

  it('leaves an index subscript alone inside an inline span', () => {
    render('Use `items[2]` here.');
    expect(code()).toEqual(['items[2]']);
    expect(citations()).toEqual([]);
  });

  it('leaves a mid-sentence triple-backtick span alone', () => {
    render('inline ```code[0]``` end');
    expect(code()).toEqual(['code[0]']);
    expect(citations()).toEqual([]);
  });

  it('leaves a triple-backtick span that starts a line alone', () => {
    // A backtick fence's info string cannot contain backticks, so this opens a
    // code span, not an unclosed fence that swallows the rest of the answer.
    render('```code[0]``` and see [1]');
    expect(code()).toEqual(['code[0]']);
    expect(citations()).toEqual(['1']);
  });

  it('closes an inline span only on a run of its own length', () => {
    // The `` run does not close the ` span, so `b[1]` is still code.
    render('Use `a`` b[1] more` end');
    expect(code()).toEqual(['a`` b[1] more']);
    expect(citations()).toEqual([]);
  });

  it('recognises a fence closed on a CRLF line', () => {
    render('```js\r\nconst a = arr[0];\r\n```\r\nSee [1].');
    expect(code()).toEqual(['const a = arr[0];']);
    expect(citations()).toEqual(['1']);
  });

  it('does not carry an inline span across a blank line', () => {
    // The blank line ends the paragraph, so the backticks never pair and
    // `bar[1]` is prose.
    render('a `foo\n\nbar[1]` end');
    expect(code()).toEqual([]);
    expect(citations()).toEqual(['1']);
  });

  it('leaves an inline span that wraps a line alone', () => {
    render('use `arr[0]\nnext` here');
    expect(code()).toEqual(['arr[0] next']);
    expect(citations()).toEqual([]);
  });

  it('leaves a tilde fence alone', () => {
    render('~~~python\nprint(row[0])\n~~~');
    expect(code()).toEqual(['print(row[0])']);
    expect(citations()).toEqual([]);
  });

  it('leaves a fence nested in a longer one alone', () => {
    // A ``` run does not close a ```` fence, so the inner block is content.
    render('````markdown\n```js\nconst a = arr[0];\n```\n````');
    expect(code()).toEqual(['```js\nconst a = arr[0];\n```']);
    expect(citations()).toEqual([]);
  });

  it('leaves a fence indented under a list item alone', () => {
    render(
      '1. Step:\n\n   ```js\n   const a = arr[0];\n\n   const b = arr[1];\n   ```',
    );
    expect(code()).toEqual(['const a = arr[0];\n\nconst b = arr[1];']);
    expect(citations()).toEqual([]);
  });

  it('leaves an unterminated fence alone while the answer is still streaming', () => {
    render('```python\nprint(row[0]', true);
    expect(code()).toEqual(['print(row[0]']);
    expect(citations()).toEqual([]);
  });

  it('leaves an unterminated inline span alone while streaming', () => {
    render('Use `items[2', true);
    expect(code()).toEqual(['items[2']);
    expect(citations()).toEqual([]);
  });

  it('leaves mermaid node labels alone', () => {
    render('```mermaid\nflowchart TD\n  A[0] --> B[1]\n```');
    expect(
      container.querySelector('[data-testid="mermaid"]')?.textContent,
    ).toBe('flowchart TD\n  A[0] --> B[1]');
    expect(citations()).toEqual([]);
  });

  it('still links a real citation in prose', () => {
    render('See source [1] for details.');
    expect(citations()).toEqual(['1']);
    expect(container.textContent).toBe('See source 1 for details.');
  });

  it('links prose citations on either side of a fence without touching it', () => {
    render('Per [1], run:\n```js\nconst a = arr[0];\n```\nthen [2].');
    expect(code()).toEqual(['const a = arr[0];']);
    expect(citations()).toEqual(['1', '2']);
  });

  it('still links a citation on an indented list continuation line', () => {
    render('- one\n    - nested [1]');
    expect(citations()).toEqual(['1']);
  });

  it('leaves an already-linked reference alone', () => {
    render('see [1](#cite-1) ok');
    expect(citations()).toEqual(['1']);
  });
});

describe('math parsing spares code', () => {
  it('leaves bash prompt escapes alone', () => {
    // `\[`/`\]` are non-printing-sequence markers in PS1; the old block rule
    // turned them into `$$` delimiters and broke the prompt.
    render('```bash\nPS1="\\[\\e[0m\\]$ "\n```');
    expect(code()).toEqual(['PS1="\\[\\e[0m\\]$ "']);
    expect(math()).toBe(0);
  });

  it('leaves bracket character classes alone in an inline span', () => {
    render('match `\\[0-9\\]` here');
    expect(code()).toEqual(['\\[0-9\\]']);
    expect(math()).toBe(0);
  });

  it('leaves dollars alone in an inline span', () => {
    render('Run `echo $HOME and $$` then `$x$`.');
    expect(code()).toEqual(['echo $HOME and $$', '$x$']);
    expect(math()).toBe(0);
  });

  it('does not link a subscript inside math', () => {
    render('value \\(a[1]\\) end, given \\[a[1]+b\\] we get [2]');
    expect(math()).toBe(2);
    expect(container.querySelectorAll('.katex-error').length).toBe(0);
    expect(citations()).toEqual(['2']);
  });
});
