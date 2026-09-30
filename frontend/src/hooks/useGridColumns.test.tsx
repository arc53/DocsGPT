import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useGridColumns } from './useGridColumns';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const atWidth = (width: number) =>
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: width >= Number(/min-width:\s*(\d+)px/.exec(query)![1]),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));

const read = async () => {
  let cols = 0;
  function Probe() {
    cols = useGridColumns();
    return null;
  }
  const root = createRoot(document.createElement('div'));
  await act(async () => root.render(<Probe />));
  await act(async () => root.unmount());
  return cols;
};

describe('useGridColumns', () => {
  afterEach(() => vi.unstubAllGlobals());

  // The tile grid: grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4.
  it.each([
    [390, 1],
    [640, 2],
    [1024, 3],
    [1280, 4],
    [1920, 4],
  ])('%ipx wide is %i columns', async (width, cols) => {
    atWidth(width);
    expect(await read()).toBe(cols);
  });
});
