import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Collapsible, CollapsibleTrigger } from './collapsible';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
});

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

const button = () => container.querySelector('button')!;
const body = () =>
  container.querySelector<HTMLElement>('[data-slot="collapsible"]')!;

function Harness({
  look,
  onOpenChange,
}: {
  look?: 'inline' | 'section';
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <CollapsibleTrigger
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          onOpenChange?.(next);
        }}
        controls="body"
        look={look}
        data-testid="toggle"
      >
        Advanced
      </CollapsibleTrigger>
      <Collapsible open={open} id="body">
        <input aria-label="Name" />
      </Collapsible>
    </>
  );
}

describe('CollapsibleTrigger', () => {
  it('is the inline link sm toggle with a turning chevron', async () => {
    await render(<Harness />);
    const b = button();
    expect(b.type).toBe('button');
    expect(b.dataset.variant).toBe('link');
    expect(b.dataset.size).toBe('sm');
    expect(b.className.split(' ')).toEqual(
      expect.arrayContaining(['-ml-3', 'w-fit', 'justify-start']),
    );
    expect(b.getAttribute('data-testid')).toBe('toggle');
    const chevron = b.querySelector('svg')!;
    expect(chevron.getAttribute('aria-hidden')).toBe('true');
    expect(chevron.getAttribute('class')).toContain('transition-transform');
    expect(chevron.getAttribute('class')).not.toContain('rotate-90');
    expect(chevron.getAttribute('class')).not.toContain('size-3');
    expect(b.textContent).toBe('Advanced');
  });

  it('wires aria-expanded and aria-controls, and toggles on click', async () => {
    const onOpenChange = vi.fn();
    await render(<Harness onOpenChange={onOpenChange} />);
    expect(button().getAttribute('aria-expanded')).toBe('false');
    expect(button().getAttribute('aria-controls')).toBe('body');
    expect(body().id).toBe('body');
    expect(body().dataset.state).toBe('closed');
    await act(async () => button().click());
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(button().getAttribute('aria-expanded')).toBe('true');
    expect(body().dataset.state).toBe('open');
    expect(button().querySelector('svg')!.getAttribute('class')).toContain(
      'rotate-90',
    );
  });

  it('draws the section look: section-toggle with an 18px semibold title', async () => {
    await render(<Harness look="section" />);
    const b = button();
    expect(b.dataset.variant).toBe('section-toggle');
    expect(b.dataset.size).toBe('sm');
    const title = b.querySelector('span')!;
    expect(title.className).toBe('text-lg font-semibold');
    expect(title.textContent).toBe('Advanced');
  });

  it('takes a small chevron', async () => {
    await render(
      <CollapsibleTrigger open={false} controls="x" chevron="sm">
        More
      </CollapsibleTrigger>,
    );
    expect(button().querySelector('svg')!.getAttribute('class')).toContain(
      'size-3',
    );
  });
});

describe('Collapsible overflow', () => {
  const inner = () => body().firstElementChild as HTMLElement;

  it('clips while it animates and stops clipping once open, so focus rings show', async () => {
    vi.useFakeTimers();
    await render(<Harness />);
    expect(inner().className).toContain('overflow-hidden');
    await act(async () => button().click());
    // Mid-animation: still clipped.
    expect(inner().className).toContain('overflow-hidden');
    await act(async () => {
      body().dispatchEvent(
        Object.assign(new Event('transitionend', { bubbles: true }), {
          propertyName: 'grid-template-rows',
        }),
      );
    });
    expect(inner().className).not.toContain('overflow-hidden');
    expect(inner().className).toContain('min-w-0');
    // Closing clips again at once.
    await act(async () => button().click());
    expect(inner().className).toContain('overflow-hidden');
  });

  it('settles without a transitionend (reduced motion)', async () => {
    vi.useFakeTimers();
    await render(<Harness />);
    await act(async () => button().click());
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    expect(inner().className).not.toContain('overflow-hidden');
  });
});
