import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './dialog';

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

describe('DialogContent', () => {
  it('uses the Modal surface: card fill, 16px corners, modal shadow, no border', async () => {
    await render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Search</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    const classes = document
      .querySelector('[data-slot="dialog-content"]')!
      .className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['bg-card', 'rounded-2xl', 'shadow-modal']),
    );
    expect(classes).not.toContain('bg-background');
    expect(classes).not.toContain('rounded-lg');
    expect(classes).not.toContain('border');
  });

  it('dims the page behind with the blurred overlay Modal uses', async () => {
    await render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Search</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    const classes = document
      .querySelector('[data-slot="dialog-overlay"]')!
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
});

describe('DialogContent matches Modal', () => {
  it('pads 32px, titles at 20px and spaces the footer 12px', async () => {
    await render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Search</DialogTitle>
          <DialogFooter>
            <button type="button">Cancel</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>,
    );
    const content = document
      .querySelector('[data-slot="dialog-content"]')!
      .className.split(' ');
    expect(content).toContain('p-8');
    expect(content).not.toContain('p-6');
    const title = document
      .querySelector('[data-slot="dialog-title"]')!
      .className.split(' ');
    expect(title).toEqual(expect.arrayContaining(['text-xl', 'leading-tight']));
    expect(title).not.toContain('text-lg');
    const footer = document
      .querySelector('[data-slot="dialog-footer"]')!
      .className.split(' ');
    expect(footer).toContain('gap-3');
    expect(footer).not.toContain('gap-2');
  });
});

describe('DialogContent layout', () => {
  it("is Modal's capped flex column with a left-aligned header", async () => {
    await render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Search</DialogTitle>
          </DialogHeader>
        </DialogContent>
      </Dialog>,
    );
    const content = document
      .querySelector('[data-slot="dialog-content"]')!
      .className.split(' ');
    expect(content).toEqual(
      expect.arrayContaining(['flex', 'flex-col', 'max-h-[85dvh]']),
    );
    expect(content).not.toContain('grid');
    const header = document
      .querySelector('[data-slot="dialog-header"]')!
      .className.split(' ');
    expect(header).toContain('text-left');
    expect(header).not.toContain('text-center');
  });
});
