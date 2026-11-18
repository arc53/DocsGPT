import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { count?: number }) =>
      options?.count === undefined ? key : `${key}:${options.count}`,
  }),
}));

import {
  Toast,
  ToastContent,
  ToastHeader,
  ToastItem,
  ToastMessage,
  ToastStatus,
  ToastTitle,
  ToastViewport,
} from './toast';
import {
  createToastAvoidRegistry,
  TOAST_STACK_BOTTOM_PX,
  ToastAvoidContext,
  useToastShown,
} from './toast-layout';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Toast', () => {
  it('is a bordered card with the toast shadow', () => {
    const html = renderToStaticMarkup(<Toast>x</Toast>);
    expect(html).toContain('shadow-toast');
    expect(html).toContain('rounded-2xl');
  });

  it('keeps its height in a capped stack, so the stack scrolls instead', () => {
    // A clipped flex item may shrink below its content: without shrink-0 the
    // capped viewport squeezes the cards and cuts off their buttons.
    expect(renderToStaticMarkup(<Toast>x</Toast>)).toMatch(
      /class="[^"]*\bshrink-0\b/,
    );
  });

  it('leaves the live region to the viewport', () => {
    const html = renderToStaticMarkup(
      <ToastViewport>
        <Toast>a</Toast>
        <Toast>b</Toast>
      </ToastViewport>,
    );
    // Exactly one live region: the viewport. Cards must not nest another.
    expect(html.match(/role="status"/g)).toHaveLength(1);
    expect(html).toMatch(
      /^<div role="status" aria-live="polite" data-slot="toast-viewport"/,
    );
    expect(renderToStaticMarkup(<Toast>x</Toast>)).not.toContain('role=');
  });

  it('lets a caller override the viewport politeness', () => {
    const html = renderToStaticMarkup(<ToastViewport aria-live="assertive" />);
    expect(html).toContain('aria-live="assertive"');
    expect(html).not.toContain('aria-live="polite"');
  });

  it('truncates the title unless it wraps', () => {
    const truncated = renderToStaticMarkup(<ToastTitle>t</ToastTitle>);
    expect(truncated).toContain('truncate');
    const wrapped = renderToStaticMarkup(<ToastTitle wrap>t</ToastTitle>);
    expect(wrapped).not.toContain('truncate');
    expect(wrapped).not.toContain('wrap=');
  });

  it('sizes the message xs by default and sm on request', () => {
    const xs = renderToStaticMarkup(<ToastMessage>m</ToastMessage>);
    expect(xs).toContain('text-xs');
    expect(xs).not.toContain('text-sm');
    const sm = renderToStaticMarkup(<ToastMessage size="sm">m</ToastMessage>);
    expect(sm).toContain('text-sm');
    expect(sm).toContain('leading-4.5');
    expect(sm).not.toContain('text-xs');
  });

  it('pads a message that is the only content under the header', () => {
    const html = renderToStaticMarkup(<ToastMessage>m</ToastMessage>);
    // pb-3 always; pt-3 only when nothing sits above it in ToastContent.
    expect(html).toContain('pb-3');
    expect(html).toContain('first:pt-3');
  });

  it('keeps a message under its row instead of below a divider', () => {
    const html = renderToStaticMarkup(
      <ToastItem label="1.png">
        <ToastStatus status="destructive" />
      </ToastItem>,
    );
    expect(html).toContain(
      '[&amp;:has(+[data-slot=toast-message])]:border-b-0',
    );
  });

  it('renders an optional icon before the label', () => {
    const html = renderToStaticMarkup(
      <ToastItem label="Conversation" icon={<ToastStatus status="warning" />}>
        <button>Review</button>
      </ToastItem>,
    );
    expect(html.indexOf('data-status="warning"')).toBeLessThan(
      html.indexOf('Conversation'),
    );
    expect(html).not.toContain('icon=');
  });

  it('tints the header by variant and colours the message', () => {
    const html = renderToStaticMarkup(
      <Toast>
        <ToastHeader variant="destructive">
          <ToastTitle>Upload failed</ToastTitle>
        </ToastHeader>
        <ToastContent>
          <ToastItem label="1.png">
            <ToastStatus status="destructive" />
          </ToastItem>
          <ToastMessage variant="destructive">
            No text could be extracted.
          </ToastMessage>
        </ToastContent>
      </Toast>,
    );
    expect(html).toContain('bg-destructive/10');
    expect(html).toContain('data-status="destructive"');
    expect(html).toContain('text-destructive');
    expect(html).toContain('No text could be extracted.');
  });

  it('never uses raw palette colours', () => {
    const html = renderToStaticMarkup(
      <Toast>
        <ToastHeader variant="success">
          <ToastTitle>Done</ToastTitle>
        </ToastHeader>
        <ToastItem label="a.md" meta="1.2k tokens">
          <ToastStatus status="success" />
        </ToastItem>
      </Toast>,
    );
    expect(html).not.toMatch(
      /\b(bg|text)-(red|green|amber|gray|black|white)\b/,
    );
  });

  it('exposes the message variant and size as data attributes', () => {
    const html = renderToStaticMarkup(
      <ToastMessage variant="destructive" size="sm">
        Failed
      </ToastMessage>,
    );
    expect(html).toContain('data-variant="destructive"');
    expect(html).toContain('data-size="sm"');
  });

  it('shows the pending status with the small Spinner, unresized', () => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(<ToastStatus status="pending" />);
    const spinner = host.querySelector('[data-slot="spinner"]')!;
    expect(spinner.getAttribute('data-size')).toBe('sm');
    const classes = spinner.getAttribute('class')!.split(' ');
    expect(classes).toContain('size-5');
    expect(classes).not.toContain('size-6');
  });
});

describe('ToastViewport layout', () => {
  let container: HTMLDivElement;
  let root: Root;
  let composer: HTMLDivElement;
  let rects: Record<string, Partial<DOMRect>>;
  let small = false;

  beforeEach(() => {
    small = false;
    // A 1440x900 window: the stack spans 1144-1432, the composer 480-1248.
    rects = {
      'toast-viewport': {
        left: 1144,
        right: 1432,
        top: 0,
        width: 288,
        height: 0,
      },
      composer: { left: 480, right: 1248, top: 780, width: 768, height: 100 },
    };
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function (this: HTMLElement) {
        const key = this.dataset.testid ?? this.dataset.slot ?? '';
        return {
          left: 0,
          right: 0,
          top: 0,
          width: 0,
          height: 0,
          ...rects[key],
        } as DOMRect;
      },
    );
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          matches: small,
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
    Object.defineProperty(window, 'innerHeight', {
      value: 900,
      configurable: true,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    composer = document.createElement('div');
    composer.dataset.testid = 'composer';
    document.body.appendChild(composer);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    composer.remove();
    vi.restoreAllMocks();
  });

  const viewport = () =>
    container.querySelector<HTMLElement>('[data-slot="toast-viewport"]')!;
  const bottom = () => viewport().style.getPropertyValue('--toast-bottom');
  const cards = (n: number) =>
    Array.from({ length: n }, (_, i) => <Toast key={i}>card {i}</Toast>);

  const renderStack = async (
    children: React.ReactNode,
    withComposer = true,
  ) => {
    const registry = createToastAvoidRegistry();
    if (withComposer) registry.add(composer);
    await act(async () => {
      root.render(
        <ToastAvoidContext.Provider value={registry}>
          <ToastViewport>{children}</ToastViewport>
        </ToastAvoidContext.Provider>,
      );
    });
    return registry;
  };

  it('rises above a composer it would cover', async () => {
    await renderStack(cards(1));
    expect(bottom()).toBe('120px');
    expect(viewport().style.getPropertyValue('--toast-max-h')).toBe('708px');
  });

  it('stays in the corner when the composer leaves room beside it', async () => {
    rects.composer = {
      left: 400,
      right: 1100,
      top: 780,
      width: 700,
      height: 100,
    };
    await renderStack(cards(1));
    expect(bottom()).toBe(`${TOAST_STACK_BOTTOM_PX}px`);
  });

  it('follows the window when it resizes', async () => {
    await renderStack(cards(1));
    rects.composer = {
      left: 300,
      right: 1000,
      top: 780,
      width: 700,
      height: 100,
    };
    await act(async () => {
      window.dispatchEvent(new Event('resize'));
    });
    expect(bottom()).toBe(`${TOAST_STACK_BOTTOM_PX}px`);
  });

  it('measures a composer that registers after the stack', async () => {
    const registry = await renderStack(cards(1), false);
    expect(bottom()).toBe(`${TOAST_STACK_BOTTOM_PX}px`);
    await act(async () => {
      registry.add(composer);
    });
    expect(bottom()).toBe('120px');
  });

  it('never blocks clicks with its own box', async () => {
    await renderStack(cards(1));
    expect(viewport().className).toContain('pointer-events-none');
    expect(viewport().className).toContain('*:pointer-events-auto');
  });

  it('scrolls only when its cards overflow the space it has', async () => {
    await renderStack(cards(2));
    expect(viewport().className).not.toContain('overflow-y-auto');
    Object.defineProperty(viewport(), 'scrollHeight', {
      value: 900,
      configurable: true,
    });
    Object.defineProperty(viewport(), 'clientHeight', {
      value: 708,
      configurable: true,
    });
    await act(async () => {
      window.dispatchEvent(new Event('resize'));
    });
    expect(viewport().className).toContain('overflow-y-auto');
  });

  it('shows every card on a wide screen', async () => {
    await renderStack(cards(3));
    const shown = container.querySelectorAll(
      '[data-slot="toast"]:not([hidden])',
    );
    expect(shown).toHaveLength(3);
    expect(container.querySelector('[data-slot="toast-more"]')).toBeNull();
  });

  it('on a phone shows the newest card and folds the rest behind "N more"', async () => {
    small = true;
    await renderStack(cards(2));
    await act(async () => {
      root.render(
        <ToastAvoidContext.Provider value={createToastAvoidRegistry()}>
          <ToastViewport>
            {[...cards(2), <Toast key="new">newest</Toast>]}
          </ToastViewport>
        </ToastAvoidContext.Provider>,
      );
    });
    const shown = () =>
      Array.from(
        container.querySelectorAll<HTMLElement>('[data-slot="toast"]'),
      ).filter((card) => !card.hidden);
    expect(shown().map((card) => card.textContent)).toEqual(['newest']);
    const more = container.querySelector<HTMLButtonElement>(
      '[data-slot="toast-more"] button',
    )!;
    expect(more.textContent).toBe('notifications.moreToasts:2');

    await act(async () => more.click());
    expect(shown()).toHaveLength(3);
    expect(more.textContent).toBe('notifications.fewerToasts');
  });

  it('tells a folded card it is off screen, until the stack opens', async () => {
    small = true;
    function Card({ label }: { label: string }) {
      const [shown, ref] = useToastShown();
      return (
        <Toast ref={ref}>
          {label}:{shown ? 'shown' : 'folded'}
        </Toast>
      );
    }
    await renderStack([<Card key="a" label="a" />, <Card key="b" label="b" />]);
    const labels = () =>
      Array.from(
        container.querySelectorAll<HTMLElement>('[data-slot="toast"]'),
      ).map((card) => card.textContent);
    expect(labels()).toEqual(['a:folded', 'b:shown']);
    const more = container.querySelector<HTMLButtonElement>(
      '[data-slot="toast-more"] button',
    )!;
    await act(async () => more.click());
    expect(labels()).toEqual(['a:shown', 'b:shown']);
  });

  it('drops the fold once one card is left', async () => {
    small = true;
    await renderStack(cards(2));
    expect(container.querySelector('[data-slot="toast-more"]')).not.toBeNull();
    await renderStack(cards(1));
    expect(container.querySelector('[data-slot="toast-more"]')).toBeNull();
    expect(
      container.querySelector<HTMLElement>('[data-slot="toast"]')!.hidden,
    ).toBe(false);
  });
});
