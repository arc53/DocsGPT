import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Sheet, SheetContent, SheetTitle } from './sheet';

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
});

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

const content = () =>
  document.querySelector<HTMLElement>('[data-slot="sheet-content"]')!;

describe('SheetContent side="bottom"', () => {
  it('is a card-coloured sheet with a rounded top that clears the home indicator', async () => {
    await render(
      <Sheet open>
        <SheetContent
          side="bottom"
          title="Tools"
          aria-describedby={undefined}
        />
      </Sheet>,
    );
    const classes = content().className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'bg-card',
        'rounded-t-2xl',
        'max-h-[90vh]',
        'pb-safe-0',
      ]),
    );
    expect(classes).not.toContain('bg-background');
    expect(classes).not.toContain('border-t');
    expect(content().dataset.side).toBe('bottom');
  });

  it('draws the grab handle first only when asked', async () => {
    await render(
      <Sheet open>
        <SheetContent
          side="bottom"
          handle
          showCloseButton={false}
          title="Tools"
          aria-describedby={undefined}
        >
          <p>Body</p>
        </SheetContent>
      </Sheet>,
    );
    const handle = content().querySelector('[data-slot="sheet-handle"]');
    expect(handle).not.toBeNull();
    expect(handle!.getAttribute('aria-hidden')).toBe('true');
    // The sr-only title comes first; the handle is the first visible child.
    const visible = Array.from(content().children).filter(
      (el) => !el.classList.contains('sr-only'),
    );
    expect(visible[0]).toBe(handle);
  });

  it('has no handle by default', async () => {
    await render(
      <Sheet open>
        <SheetContent
          side="bottom"
          title="Tools"
          aria-describedby={undefined}
        />
      </Sheet>,
    );
    expect(content().querySelector('[data-slot="sheet-handle"]')).toBeNull();
  });

  it('leaves the side sheets on the page background with their border', async () => {
    await render(
      <Sheet open>
        <SheetContent side="right" title="Trace" aria-describedby={undefined} />
      </Sheet>,
    );
    const classes = content().className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['bg-background', 'border-l']),
    );
    expect(classes).not.toContain('rounded-t-2xl');
  });
});

describe('SheetOverlay', () => {
  it('uses the blurred scrim every Modal uses', async () => {
    await render(
      <Sheet open>
        <SheetContent side="right" title="Trace" aria-describedby={undefined} />
      </Sheet>,
    );
    const classes = document
      .querySelector('[data-slot="sheet-overlay"]')!
      .className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'bg-black/25',
        'backdrop-blur-xs',
        'dark:bg-black/50',
      ]),
    );
    expect(classes).not.toContain('bg-black/50');
  });

  it('hides the X on a handled bottom sheet by default', async () => {
    await render(
      <Sheet open>
        <SheetContent
          side="bottom"
          handle
          title="Tools"
          aria-describedby={undefined}
        />
      </Sheet>,
    );
    expect(
      document.querySelector(
        '[data-slot="sheet-content"] [aria-label="Close"]',
      ),
    ).toBeNull();
  });

  it('SheetTitle defaults to the 20px title', async () => {
    await render(
      <Sheet open>
        <SheetContent>
          <SheetTitle>Run details</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    const title = document.querySelector('[data-slot="sheet-title"]');
    expect(title?.className).toContain('text-xl leading-tight font-semibold');
  });
});
