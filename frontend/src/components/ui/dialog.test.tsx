import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Dialog, DialogContent, DialogTitle } from './dialog';

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
