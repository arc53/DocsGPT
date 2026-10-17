import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { CodeBlock, CodeFrame, CodePanel, CopyField } from './code-block';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('code-block', () => {
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

  const render = (node: React.ReactNode) => act(() => root.render(node));
  const pre = () => container.querySelector('pre')!;
  const copyButtons = () =>
    container.querySelectorAll('button[aria-label="conversation.copy"]');

  describe('CodeBlock', () => {
    it('is a mono pre in a filled sm Card by default', () => {
      render(<CodeBlock>{'{ "a": 1 }'}</CodeBlock>);
      const card = container.firstElementChild as HTMLElement;
      expect(card.dataset.slot).toBe('card');
      expect(card.className).toContain('bg-muted');
      expect(card.className).toContain('p-3');
      expect(pre().className).toContain('font-mono');
      expect(pre().className).toContain('text-xs');
      expect(pre().className).toContain('whitespace-pre-wrap');
      expect(pre().className).toContain('wrap-break-word');
      // One line-height everywhere: never leading-relaxed.
      expect(pre().className).not.toContain('leading-relaxed');
      expect(pre().textContent).toBe('{ "a": 1 }');
    });

    it('takes a subtle Card, or no box at all when bare', () => {
      render(<CodeBlock surface="subtle">x</CodeBlock>);
      const card = container.firstElementChild as HTMLElement;
      expect(card.className).toContain('bg-background');
      expect(card.className).toContain('border');
      render(<CodeBlock surface="bare">x</CodeBlock>);
      expect(container.firstElementChild!.tagName).toBe('PRE');
      expect(container.querySelector('[data-slot="card"]')).toBeNull();
    });

    it('puts the scroll cap on an inner div, never on the Card', () => {
      const caps = { sm: 'max-h-40', md: 'max-h-60', lg: 'max-h-80' };
      for (const [size, cls] of Object.entries(caps)) {
        render(
          <CodeBlock maxHeight={size as keyof typeof caps}>{size}</CodeBlock>,
        );
        const card = container.firstElementChild as HTMLElement;
        expect(card.className).not.toContain('max-h-');
        const scroller = pre().parentElement!;
        expect(scroller).not.toBe(card);
        expect(scroller.className).toContain(cls);
        expect(scroller.className).toContain('overflow-y-auto');
        expect(scroller.className).toContain('scrollbar-overlay');
      }
    });

    it('scrolls inside a parent-sized box with maxHeight="parent"', () => {
      render(
        <CodeBlock surface="bare" maxHeight="parent" className="h-full p-4">
          x
        </CodeBlock>,
      );
      const scroller = container.firstElementChild as HTMLElement;
      expect(scroller.tagName).toBe('DIV');
      expect(scroller.className).toContain('min-h-0');
      expect(scroller.className).toContain('overflow-auto');
      expect(scroller.className).toContain('h-full p-4');
    });

    it('fills a full-pane viewer with surface="pane"', () => {
      render(<CodeBlock surface="pane">x</CodeBlock>);
      const pane = container.firstElementChild as HTMLElement;
      expect(pane.tagName).toBe('DIV');
      expect(pane.className).toContain('h-full');
      expect(pane.className).toContain('p-4');
      expect(pane.className).toContain('overflow-auto');
      expect(container.querySelector('[data-slot="card"]')).toBeNull();
    });

    it('sets the tone, the wrap and the sans face', () => {
      render(
        <CodeBlock surface="bare" tone="destructive" wrap="anywhere">
          x
        </CodeBlock>,
      );
      expect(pre().className).toContain('text-destructive');
      expect(pre().className).toContain('wrap-anywhere');
      expect(pre().className).not.toContain('wrap-break-word');
      render(
        <CodeBlock surface="bare" tone="muted" font="sans">
          x
        </CodeBlock>,
      );
      expect(pre().className).toContain('text-muted-foreground');
      expect(pre().className).not.toContain('font-mono');
    });
  });

  describe('CopyField', () => {
    it('is a filled Card row with the value and one icon-only copy button', () => {
      render(<CopyField value="https://x/callback" wrap="anywhere" />);
      const card = container.firstElementChild as HTMLElement;
      expect(card.dataset.slot).toBe('card');
      expect(card.className).toContain('bg-muted');
      expect(card.className).toContain('flex-row');
      expect(card.className).toContain('items-start');
      expect(pre().textContent).toBe('https://x/callback');
      expect(pre().className).toContain('select-all');
      expect(pre().className).toContain('wrap-anywhere');
      // py-2 on the 16px line puts the first line on the 32px button centre.
      expect(pre().className).toContain('py-2');
      const buttons = copyButtons();
      expect(buttons).toHaveLength(1);
      expect((buttons[0] as HTMLElement).dataset.size).toBe('icon-sm');
      // Icon-only: no visible "Copy" text label.
      expect(buttons[0].textContent).not.toContain('conversation.copy');
    });

    it('passes a test id to the value and shows a placeholder without a button', () => {
      render(
        <CopyField value="" data-testid="pat">
          …
        </CopyField>,
      );
      expect(container.querySelector('[data-testid="pat"]')!.textContent).toBe(
        '…',
      );
      expect(copyButtons()).toHaveLength(0);
    });

    it('sets a display-size code centred on the button', () => {
      render(<CopyField value="KQ7M-4TXB" size="display" />);
      const card = container.firstElementChild as HTMLElement;
      expect(card.className).toContain('items-center');
      expect(pre().className).toContain('text-3xl');
      expect(pre().className).toContain('text-center');
      expect(pre().className).toContain('tracking-widest');
      expect((copyButtons()[0] as HTMLElement).dataset.size).toBe('icon-sm');
    });
  });

  describe('CodePanel', () => {
    it('is the answer-surface panel with a muted label and one copy button', () => {
      render(
        <CodePanel title="Arguments" copyText='{"q":1}'>
          <CodeBlock surface="bare" maxHeight="lg">
            {'{"q":1}'}
          </CodeBlock>
        </CodePanel>,
      );
      const panel = container.firstElementChild as HTMLElement;
      expect(panel.className).toContain('bg-answer-surface');
      expect(panel.className).toContain('rounded-xl');
      expect(panel.textContent).toContain('Arguments');
      const buttons = copyButtons();
      expect(buttons).toHaveLength(1);
      expect((buttons[0] as HTMLElement).dataset.size).toBe('icon-sm');
    });
  });

  describe('CodeFrame', () => {
    it('draws the bordered frame with a labelled header and the copy button first', () => {
      render(
        <CodeFrame
          label="python"
          copyText="print(1)"
          actions={<button type="button">Code</button>}
        >
          <div>body</div>
        </CodeFrame>,
      );
      const frame = container.firstElementChild as HTMLElement;
      expect(frame.className).toContain('rounded-xl');
      expect(frame.className).toContain('border');
      expect(frame.className).toContain('overflow-hidden');
      const header = frame.firstElementChild as HTMLElement;
      expect(header.className).toContain('bg-answer-surface');
      expect(header.textContent).toContain('python');
      const buttons = header.querySelectorAll('button');
      expect(buttons[0].getAttribute('aria-label')).toBe('conversation.copy');
      expect((buttons[0] as HTMLElement).dataset.size).toBe('icon-sm');
      expect(buttons[1].textContent).toBe('Code');
      expect(frame.textContent).toContain('body');
    });

    it('takes the muted header outside chat', () => {
      render(
        <CodeFrame label="sql" copyText="x" surface="muted">
          <div />
        </CodeFrame>,
      );
      const header = container.firstElementChild!
        .firstElementChild as HTMLElement;
      expect(header.className).toContain('bg-muted');
      expect(header.className).not.toContain('bg-answer-surface');
    });
  });
});
