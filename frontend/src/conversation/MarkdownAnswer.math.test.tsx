/**
 * Math must render as math, and only math.
 *
 * ``processMarkdownContent`` rewrote inline ``\(x\)`` to ``$x$`` while
 * remark-math runs with ``singleDollarTextMath: false``, so every inline span
 * rendered as the literal text ``$x$`` (students asked "what does $ mean").
 * A one-line ``\[ … \]`` became ``$$ … $$`` mid-paragraph, which remark-math
 * reads as *inline* math, so display equations shrank into the sentence. And a
 * citation pass over the raw string turned ``$$a[1]$$`` into a link inside the
 * formula. Math is now parsed by the markdown parser itself; these tests only
 * look at what renders.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Records the markdown each ReactMarkdown instance renders.
const markdownRenders = vi.hoisted(() => vi.fn());
vi.mock('react-markdown', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-markdown')>();
  return {
    ...actual,
    default: (props: Parameters<typeof actual.default>[0]) => {
      markdownRenders(props.children);
      return actual.default(props);
    },
  };
});
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

type RenderOptions = {
  isStreaming?: boolean;
  sourceCount?: number;
  onOpenSource?: (index: number) => void;
};

function render(content: string, options: RenderOptions = {}) {
  act(() => root.render(<MarkdownAnswer content={content} {...options} />));
  const all = container.querySelectorAll('.katex').length;
  const display = container.querySelectorAll('.katex-display').length;
  const clone = container.cloneNode(true) as HTMLElement;
  clone
    .querySelectorAll('.katex, .katex-error')
    .forEach((node) => node.remove());
  return {
    inline: all - display,
    display,
    errors: container.querySelectorAll('.katex-error').length,
    text: clone.textContent ?? '',
  };
}

/** TeX source of every rendered formula, in order. */
function formulas() {
  return Array.from(
    container.querySelectorAll(
      '.katex annotation[encoding="application/x-tex"]',
    ),
  ).map((node) => node.textContent);
}

/** Citation pills, the only buttons these answers render. */
function citations() {
  return Array.from(container.querySelectorAll('button')).map(
    (node) => node.textContent,
  );
}

describe('backslash delimiters', () => {
  it('renders inline \\( \\) math as inline KaTeX, not a literal $', () => {
    const out = render('The velocity is \\(v = u + at\\) at time t.');
    expect(out.inline).toBe(1);
    expect(out.display).toBe(0);
    expect(out.text).not.toContain('$');
    expect(out.text).toContain('at time t.');
  });

  it.each([
    ['at the start of a line', '\\(v\\) is the final velocity.'],
    ['in a list item', '- speed \\(v\\) in metres'],
    ['in a table cell', '| q | f |\n|---|---|\n| v | \\(v=u+at\\) |'],
    ['wrapping a line', 'where \\(a +\nb\\) holds'],
    ['in a heading', '## Speed \\(v\\)'],
    ['inside bold', '**the speed \\(v\\)**'],
  ])('renders inline math %s', (_, source) => {
    const out = render(source);
    expect(out.inline).toBe(1);
    expect(out.errors).toBe(0);
    expect(out.text).not.toContain('$');
  });

  it('keeps a line break inside inline math as whitespace', () => {
    // `\alpha` followed by a newline must not fuse into `\alphab`.
    render('then \\(\\alpha\nb\\) holds');
    expect(formulas()).toEqual(['\\alpha\nb']);
  });

  it('renders a dollar sign inside inline math without a KaTeX error', () => {
    const out = render('cost \\(C = \\$5 n\\) here');
    expect(out.inline).toBe(1);
    expect(out.errors).toBe(0);
  });

  it('renders a one-line \\[ \\] on its own line as display math', () => {
    const out = render(
      'Displacement:\n\\[ s = ut + \\tfrac12 at^2 \\]\nwhere u is speed.',
    );
    expect(out.display).toBe(1);
    expect(out.inline).toBe(0);
    expect(out.text).toContain('Displacement:');
    expect(out.text).toContain('where u is speed.');
  });

  it('renders a one-line \\[ \\] inside a list item as display math', () => {
    const out = render(
      '1. Step one:\n\n   \\[ v^2 = u^2 + 2as \\]\n\n2. Step two',
    );
    expect(out.display).toBe(1);
    expect(container.querySelectorAll('ol > li').length).toBe(2);
  });

  it('renders multi-line \\[ \\] as display math', () => {
    expect(render('Then:\n\n\\[\ns = ut\n\\]\n\nDone.').display).toBe(1);
    expect(render('\\[\na+b=c\n\\]').display).toBe(1);
  });

  it('does not read math lines as markdown structure', () => {
    // A lone `=` under a line is a setext heading and a `- ` line a list item,
    // outside math.
    const out = render('\\[\nx\n=\ny\n- z\n\\]');
    expect(out.display).toBe(1);
    expect(container.querySelector('h1, ul')).toBeNull();
    expect(formulas()).toEqual(['x\n=\ny\n- z']);
  });

  it('renders mid-sentence \\[ \\] as math', () => {
    const out = render('So \\[ s = ut \\] holds.');
    expect(out.inline + out.display).toBe(1);
    expect(out.text).toContain('holds.');
  });

  it('keeps the rest of the answer when a line opens with \\[ \\] and goes on', () => {
    // A line-start `\[` is a display block only when its `\]` ends the line;
    // otherwise it must not swallow everything after it.
    const out = render('\\[a+b=c\\] and more text\n\nNext paragraph.');
    expect(out.inline).toBe(1);
    expect(out.display).toBe(0);
    expect(out.text).toContain('and more text');
    expect(container.querySelectorAll('p').length).toBe(2);
  });

  it.each([
    ['\\[x=1\\tag{1}\\]', '\\tag'],
    ['\\[\\begin{aligned}x&=1\\end{aligned}\\]', 'aligned'],
    ['where \\(x = 1 \\tag{2}\\) holds', 'inline \\tag'],
  ])('renders %s as display math', (source) => {
    const out = render(source);
    expect(out.display).toBe(1);
    expect(out.errors).toBe(0);
  });

  it('renders display math inside a blockquote', () => {
    const out = render('> \\[\n> x\n> =\n> y\n> \\]');
    expect(out.display).toBe(1);
    expect(container.querySelector('blockquote .katex-display')).not.toBeNull();
    expect(formulas()).toEqual(['x\n=\ny']);
  });

  it('renders display math inside a list item', () => {
    const out = render('- \\[\n  x\n  =\n  y\n  \\]');
    expect(out.display).toBe(1);
    expect(container.querySelector('li .katex-display')).not.toBeNull();
  });

  it('does not close a display block across the end of a blockquote', () => {
    const out = render('> \\[\n> x\n> =\n\ny\n\\]\n\nNext section\n=');
    expect(out.inline + out.display + out.errors).toBe(0);
  });

  it('does not render an unclosed \\( as math', () => {
    const out = render('Using \\(v = u');
    expect(out.inline + out.display + out.errors).toBe(0);
  });

  it('does not render an unclosed \\[ block as math', () => {
    const out = render('Then\n\n\\[\nv = u\n\nand the rest.');
    expect(out.inline + out.display + out.errors).toBe(0);
    expect(out.text).toContain('and the rest.');
  });

  it('keeps an escaped task checkbox as text', () => {
    const out = render('- \\[ \\] todo\n- done');
    expect(out.inline + out.display + out.errors).toBe(0);
    expect(out.text).toContain('todo');
    expect(container.querySelectorAll('li').length).toBe(2);
  });

  it('keeps escaped index brackets as text', () => {
    const out = render('arr\\[0\\] and arr\\[1\\]');
    expect(out.inline + out.display).toBe(0);
    expect(out.text).toContain('arr[0] and arr[1]');
  });

  it('keeps nested \\( \\) in one span', () => {
    // KaTeX cannot typeset a nested `\(`, but the span must not end at the
    // inner `\)` and leak the outer one into the text.
    const out = render('\\(a + \\(b + c\\)\\) end');
    expect(out.inline + out.errors).toBe(1);
    expect(out.text.trim()).toBe('end');
  });

  it('does not mistake a \\[ \\] after inline code for its own line', () => {
    const out = render('Use `f` \\[x\\]\nnext');
    expect(out.inline + out.display).toBe(1);
    expect(out.text).not.toContain('$');
  });

  it('leaves \\( \\) inside code untouched', () => {
    const out = render('Type `\\(x\\)` literally.');
    expect(out.inline).toBe(0);
    expect(container.querySelector('code')?.textContent).toBe('\\(x\\)');
  });

  it('leaves bash prompt escapes in a fence untouched', () => {
    const out = render('```bash\nPS1="\\[\\e[0m\\]$ "\n```');
    expect(out.inline + out.display).toBe(0);
    expect(container.textContent).toContain('PS1="\\[\\e[0m\\]$ "');
  });
});

describe('dollar delimiters', () => {
  it.each([
    'from $2bn to at least $4bn per operation starting Sept 9.',
    'Price is $50 and $100',
    '$50 is $20 + $30',
    'Total: $29.50 plus tax',
    'Revenue: $5M to $10M, funding: $1.5B, price: $5K',
    '$250k is 25% of $1M',
    'Bitcoin: $0.00001234, Gas: $3.999, Rate: $1.234567890',
    'The total is $1157.90 (existing) + $500 (new investment) = $1657.90.',
    'a $100-$200 range',
    'a $100–$200 range',
    'in the $10k-$20k band',
    '- **Total Savings**: $500 + $200 + $150 = $850',
    'Cela coûte 100$ et 200$ en Europe',
    'A single $ sign should not be converted',
    'The price hit $79,455 on',
    'Currency $100 and\nthen $200 later',
    'The cost is $',
    'Use $variable in the code',
    '| Date | Price | Note |\n|---|---|---|\n| Aug 21 | $77,300, peak $79,455 | White House Clarity Act push |',
    'It costs $5 and $10 in total.',
    'Plans range between $5-$10 per seat.',
    'Price: $19.99/month or $199/year.',
    'Revenue grew from $3.2B to $4.1B.',
    'Price is $5 (was $10).',
    '| Plan | Price |\n|---|---|\n| Basic | $5 |\n| Pro | $10 |',
  ])('leaves currency as text: %s', (source) => {
    const out = render(source);
    expect(out.inline + out.display + out.errors).toBe(0);
    const amount = source.match(/\$\d[\d.,]*|\d+\$/);
    if (amount) expect(out.text).toContain(amount[0]);
  });

  it.each([
    ['Inline math: $x^2 + y^2 = z^2$', 1],
    ['the answer is $3$.', 1],
    ['an eigenvalue of $-1$ is expected', 1],
    ['the $n$th term', 1],
    ['The set is defined as $\\{x | x > 0\\}$.', 1],
    ['Calculate $\\text{Total} = \\$500 + \\$200$', 1],
    ['The equation $12 \\times 12 = 144$ is simple', 1],
    ['Price $100 then equation $x + y = z$ then another price $50', 1],
    ['Formula $x^2$ costs $25', 1],
  ])('renders %s as math', (source, count) => {
    const out = render(source);
    expect(out.inline).toBe(count);
    expect(out.errors).toBe(0);
  });

  it('keeps the price beside a formula', () => {
    render('Cost is $5 per unit and $x$ units.');
    expect(formulas()).toEqual(['x']);
    expect(container.textContent).toContain('$5 per unit');
  });

  it('does not form emphasis out of math', () => {
    const out = render('terms $a_1 + b_2$ and $c_{i}^{*}$ here');
    expect(out.inline).toBe(2);
    expect(container.querySelector('em, strong')).toBeNull();
  });

  it('renders chemistry with mhchem', () => {
    const out = render('$\\ce{H2O}$ and $\\pu{123 J}$');
    expect(out.inline).toBe(2);
    expect(out.errors).toBe(0);
  });

  it.each([
    [
      'a code span',
      'The error "invalid $lookup namespace" occurs when using `$lookup` operator',
    ],
    ['escaped dollars', 'Already escaped \\$50 and \\$100'],
    ['a line break', 'This has $x\ny$ which spans lines'],
    ['an unbalanced brace', 'weird $a}b$ y'],
    [
      'shell PIDs in a fence',
      '```bash\npstree -p $$\necho $$\n```\n\nSome text after.',
    ],
  ])('renders no math across %s', (_, source) => {
    const out = render(source);
    expect(out.inline + out.display + out.errors).toBe(0);
  });

  it('renders math only outside a fence', () => {
    const out = render('```\n$100\n$variable\n```\n\nOutside $x^2$');
    expect(out.inline).toBe(1);
    expect(container.querySelector('code')?.textContent).toContain('$variable');
  });

  it('renders a $$ paragraph as display math', () => {
    const out = render('text\n\n$$E=mc^2$$\n\nmore');
    expect(out.display).toBe(1);
    expect(out.text).toContain('more');
  });

  it('keeps mid-line $$ math inline', () => {
    const out = render('so $$E=mc^2$$ holds');
    expect(out.inline).toBe(1);
    expect(out.display).toBe(0);
  });

  it('renders $$ with \\begin on the fence line', () => {
    const out = render(
      '$$\\begin{aligned}\na&=b\\\\\nc&=d\n\\end{aligned}$$\n\nAfter.',
    );
    expect(out.display).toBe(1);
    expect(out.errors).toBe(0);
    expect(out.text).toContain('After.');
  });
});

describe('citations', () => {
  it('links citations next to inline math and renders the math', () => {
    const out = render('Newton: \\(F=ma\\) [1] and \\(p=mv\\)[2].');
    expect(out.inline).toBe(2);
    expect(citations()).toEqual(['1', '2']);
  });

  it('never links a bracket inside math', () => {
    const out = render('$$a[1]$$ and [3]');
    expect(formulas()).toEqual(['a[1]']);
    expect(out.errors).toBe(0);
    expect(citations()).toEqual(['3']);
  });

  it('never links a bracket inside single-dollar math', () => {
    const out = render('value $a[1]$ end [2]');
    expect(citations()).toEqual(['2']);
    expect(out.errors).toBe(0);
  });

  it.each([
    ['**[1]** and [2][3]', ['1', '2', '3']],
    ['see `row[0]` and [4]', ['4']],
    ['[link](https://x.com) [1]', ['1']],
    ['- one\n    - nested [1]', ['1']],
    ['Per [1], run:\n```js\nconst a = arr[0];\n```\nthen [2].', ['1', '2']],
  ])('links %s', (source, expected) => {
    render(source);
    expect(citations()).toEqual(expected);
  });

  it('leaves code and diagram labels alone', () => {
    render('```python\nprint(row[0])\n```');
    expect(container.textContent).toContain('print(row[0])');
    expect(citations()).toEqual([]);
  });

  it('keeps a reference-style link a link', () => {
    render('See [the docs][1].\n\n[1]: https://example.com');
    expect(
      container.querySelector('a[href="https://example.com"]'),
    ).not.toBeNull();
    expect(citations()).toEqual([]);
  });

  it('links only citations within the number of sources', () => {
    render('Per [1], [2] and [0] and [7].', { sourceCount: 2 });
    expect(citations()).toEqual(['1', '2']);
    expect(container.textContent).toContain('[0] and [7]');
  });

  it.each([
    ['Both agree [1, 2].', ['1', '2']],
    ['Tight [3,4]', ['3', '4']],
    ['See [1][2].', ['1', '2']],
    ['Not a list [a, b]', []],
  ])('links each number of a grouped citation: %s', (source, expected) => {
    render(source);
    expect(citations()).toEqual(expected);
  });

  it('keeps a grouped number beyond the sources as text', () => {
    render('Per [1, 9].', { sourceCount: 2 });
    expect(citations()).toEqual(['1']);
    expect(container.textContent).toContain('[9]');
  });

  it('leaves an escaped grouped citation alone', () => {
    render('arr\\[1, 2\\] here');
    expect(citations()).toEqual([]);
  });

  it('links no citation when the answer has no sources', () => {
    render('Per [1].', { sourceCount: 0 });
    expect(citations()).toEqual([]);
    expect(container.textContent).toContain('[1]');
  });
});

describe('citation pills', () => {
  function click(label: string) {
    const pill = Array.from(container.querySelectorAll('button')).find(
      (node) => node.textContent === label,
    );
    act(() => pill?.click());
  }

  it('opens the cited source by its index', () => {
    const onOpenSource = vi.fn();
    render('Per [2] and [5].', { sourceCount: 5, onOpenSource });
    click('2');
    click('5');
    expect(onOpenSource.mock.calls).toEqual([[1], [4]]);
  });

  it('opens each number of a grouped citation on its own', () => {
    const onOpenSource = vi.fn();
    render('Both [1, 3].', { sourceCount: 3, onOpenSource });
    click('3');
    expect(onOpenSource).toHaveBeenCalledWith(2);
  });
});

describe('mermaid', () => {
  it('renders a closed mermaid fence as a diagram, source untouched', () => {
    render(
      'Intro [1]\n\n```mermaid\nflowchart TD\n  A[0] --> B[1]\n```\n\nOutro',
    );
    expect(
      container.querySelector('[data-testid="mermaid"]')?.textContent,
    ).toBe('flowchart TD\n  A[0] --> B[1]');
    expect(citations()).toEqual(['1']);
    expect(container.textContent).toContain('Outro');
  });

  it('shows an unclosed mermaid fence as code while it streams', () => {
    render('```mermaid\nflowchart TD\n  A --> B', { isStreaming: true });
    expect(container.querySelector('[data-testid="mermaid"]')).toBeNull();
  });
});

describe('streaming', () => {
  it('closes an open $$ block while streaming', () => {
    const out = render('$$\nx = 1\ny = 2', { isStreaming: true });
    expect(out.display).toBe(1);
  });

  it('closes an open inline $$ while streaming', () => {
    const out = render('Text with $$formula', { isStreaming: true });
    expect(out.inline).toBe(1);
    expect(out.text).not.toContain('$');
  });

  it('closes an open \\[ block while streaming', () => {
    const out = render('Then:\n\n\\[\nv = u', { isStreaming: true });
    expect(out.display).toBe(1);
  });

  it('closes open bold before an open formula, not after it', () => {
    // Appended to the end, `**` turned the closing fence into `$$**`.
    const out = render('Energy is **the work it takes\n$$\nE = mc', {
      isStreaming: true,
    });
    expect(out.display).toBe(1);
    expect(out.errors).toBe(0);
    expect(formulas()).toEqual(['E = mc']);
  });

  it('holds back an inline $$ with nothing after it yet', () => {
    const out = render('Then **bold** and $$', { isStreaming: true });
    expect(out.inline + out.display + out.errors).toBe(0);
    expect(out.text).not.toContain('$');
  });

  it('does not render an unclosed \\( while streaming', () => {
    const out = render('Using \\(v = u', { isStreaming: true });
    expect(out.inline + out.display + out.errors).toBe(0);
  });

  it('leaves a trailing $ alone', () => {
    const out = render('The cost is $', { isStreaming: true });
    expect(out.inline + out.display).toBe(0);
    expect(out.text).toContain('The cost is $');
  });

  it('closes open bold while streaming', () => {
    render('Text **bold', { isStreaming: true });
    expect(container.querySelector('strong')?.textContent).toBe('bold');
  });

  it('does not add $$ inside an open code fence', () => {
    render('```bash\necho $$', { isStreaming: true });
    expect(container.querySelector('code')?.textContent).toBe('echo $$');
  });

  it('does not heal once the answer is complete', () => {
    render('Text **bold');
    expect(container.querySelector('strong')).toBeNull();
  });

  it('shows a formula that cannot render yet in the muted colour', () => {
    const out = render('$$\n\\frac{a}{', { isStreaming: true });
    expect(out.errors).toBe(1);
    const error = container.querySelector<HTMLElement>('.katex-error');
    expect(error?.getAttribute('style')).toContain('var(--muted-foreground)');
  });
});

describe('block rendering', () => {
  it('re-renders only the block that changed', () => {
    render('First \\(x^2\\) [1].\n\nSecond', { isStreaming: true });
    markdownRenders.mockClear();
    render('First \\(x^2\\) [1].\n\nSecond paragraph grows', {
      isStreaming: true,
    });
    // The first paragraph, formula and all, is not parsed or typeset again.
    expect(markdownRenders.mock.calls).toEqual([['Second paragraph grows']]);
    expect(container.textContent).toContain('Second paragraph grows');
  });

  it('keeps footnotes working across blocks', () => {
    render('Claim[^1].\n\nMore.\n\n[^1]: The note.');
    expect(
      container.querySelector('a[href="#user-content-fn-1"]'),
    ).not.toBeNull();
  });
});
