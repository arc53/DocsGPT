import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { Select, SelectContent, SelectItem, SelectTrigger } from './select';

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let host: HTMLDivElement | null = null;

afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe('SelectItem', () => {
  it('fills the highlighted item, so keyboard navigation is visible', () => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root!.render(
        <Select open value="a">
          <SelectTrigger aria-label="Rows">a</SelectTrigger>
          <SelectContent>
            <SelectItem value="a">A</SelectItem>
          </SelectContent>
        </Select>,
      );
    });
    const item = document.querySelector('[data-slot="select-item"]');
    expect(item).not.toBeNull();
    // Radix sets data-highlighted on pointer hover and on arrow-key focus alike.
    expect(item!.className).toContain('data-highlighted:bg-muted');
  });
});
