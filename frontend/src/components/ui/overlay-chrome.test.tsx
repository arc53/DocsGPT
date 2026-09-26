import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Dialog, DialogContent, DialogTitle } from './dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from './dropdown-menu';
import { Modal } from './modal';
import { Sheet, SheetContent } from './sheet';

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

const closeButton = () =>
  document.querySelector<HTMLButtonElement>('button[aria-label="Close"]');

describe('close buttons on overlays', () => {
  const cases: [string, () => React.ReactElement][] = [
    [
      'Modal',
      () => (
        <Modal open onOpenChange={() => undefined} title="Create access token">
          Body
        </Modal>
      ),
    ],
    [
      'DialogContent',
      () => (
        <Dialog open>
          <DialogContent aria-describedby={undefined}>
            <DialogTitle>Search</DialogTitle>
          </DialogContent>
        </Dialog>
      ),
    ],
    [
      'SheetContent',
      () => (
        <Sheet open>
          <SheetContent title="Trace" aria-describedby={undefined} />
        </Sheet>
      ),
    ],
  ];

  it.each(cases)(
    '%s closes with a 32px ghost-muted icon Button',
    async (_name, element) => {
      await render(element());
      const button = closeButton();
      expect(button).not.toBeNull();
      expect(button!.dataset.variant).toBe('ghost-muted');
      expect(button!.dataset.size).toBe('icon-sm');
      expect(button!.className).toContain('absolute');
    },
  );

  it.each(cases)(
    '%s shows the focus ring on keyboard focus only',
    async (_name, element) => {
      await render(element());
      const classes = closeButton()!.className.split(' ');
      expect(classes).toContain('focus-visible:ring-3');
      expect(classes.some((c) => c.startsWith('focus:'))).toBe(false);
      expect(classes).not.toContain('focus:ring-2');
    },
  );
});

describe('overlay elevation', () => {
  it('DialogContent is a modal surface', async () => {
    await render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Search</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    const content = document.querySelector('[data-slot="dialog-content"]')!;
    expect(content.className).toContain('shadow-modal');
    expect(content.className).not.toContain('shadow-lg');
    // Centred with scale steps, not bracketed percentages.
    expect(content.className).toContain('-translate-x-1/2');
    expect(content.className).not.toContain('translate-x-[-50%]');
  });

  it('DropdownMenuSubContent floats like the menu it opens from', async () => {
    await render(
      <DropdownMenu open>
        <DropdownMenuTrigger>Open</DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuSub open>
            <DropdownMenuSubTrigger>Move to</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>Sales</DropdownMenuSubContent>
          </DropdownMenuSub>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    const sub = document.querySelector(
      '[data-slot="dropdown-menu-sub-content"]',
    )!;
    expect(sub.className).toContain('shadow-md');
    expect(sub.className).not.toContain('shadow-lg');
  });
});
