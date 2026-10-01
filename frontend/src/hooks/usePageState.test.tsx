import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useClientPage, usePageParam, usePageSize } from './usePageState';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('usePageParam', () => {
  let container: HTMLDivElement;
  let root: Root;
  let state: ReturnType<typeof usePageParam>;
  let search = '';

  function Probe() {
    state = usePageParam('page');
    search = useLocation().search;
    return null;
  }

  const render = async (entry: string) => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[entry]}>
          <Probe />
        </MemoryRouter>,
      );
    });
  };

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('reads the page from the URL, 1 when absent or invalid', async () => {
    await render('/settings/sources?page=3');
    expect(state[0]).toBe(3);
    await act(async () => root.unmount());
    root = createRoot(container);
    await render('/settings/sources?page=abc');
    expect(state[0]).toBe(1);
  });

  it('writes the page and keeps other params, dropping page=1', async () => {
    await render('/settings/sources?tab=all');
    await act(async () => state[1](4));
    expect(state[0]).toBe(4);
    expect(search).toBe('?tab=all&page=4');
    await act(async () => state[1](1));
    expect(state[0]).toBe(1);
    expect(search).toBe('?tab=all');
  });
});

describe('usePageSize', () => {
  let container: HTMLDivElement;
  let root: Root;
  let state: ReturnType<typeof usePageSize>;

  function Probe() {
    state = usePageSize('DocsGPTPageSize:test', [12, 24, 48]);
    return null;
  }

  const render = async () => {
    root = createRoot(container);
    await act(async () => root.render(<Probe />));
  };

  beforeEach(() => {
    container = document.createElement('div');
    localStorage.clear();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('starts at the smallest option', async () => {
    await render();
    expect(state[0]).toBe(12);
  });

  it('remembers the chosen size', async () => {
    await render();
    await act(async () => state[1](48));
    expect(state[0]).toBe(48);
    await act(async () => root.unmount());
    await render();
    expect(state[0]).toBe(48);
  });

  it('ignores a stored size that is no longer an option', async () => {
    localStorage.setItem('DocsGPTPageSize:test', '10');
    await render();
    expect(state[0]).toBe(12);
  });
});

describe('usePageSize default', () => {
  let root: Root;
  let size = 0;

  function Probe({ fallback }: { fallback: number }) {
    size = usePageSize('DocsGPTPageSize:default', [12, 24, 48], fallback)[0];
    return null;
  }

  beforeEach(() => localStorage.clear());
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('starts at the given default, and a stored size still wins', async () => {
    root = createRoot(document.createElement('div'));
    await act(async () => root.render(<Probe fallback={24} />));
    expect(size).toBe(24);
    await act(async () => root.unmount());
    localStorage.setItem('DocsGPTPageSize:default', '48');
    root = createRoot(document.createElement('div'));
    await act(async () => root.render(<Probe fallback={24} />));
    expect(size).toBe(48);
  });
});

describe('useClientPage', () => {
  let root: Root;
  let state: ReturnType<typeof useClientPage<number>>;
  const items = Array.from({ length: 100 }, (_, i) => i);

  function Probe({ list, resetKey }: { list: number[]; resetKey: string }) {
    state = useClientPage(list, 48, resetKey);
    return null;
  }

  const render = async (list: number[], resetKey = '') => {
    await act(async () =>
      root.render(<Probe list={list} resetKey={resetKey} />),
    );
  };

  beforeEach(() => {
    root = createRoot(document.createElement('div'));
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  it('slices the current page', async () => {
    await render(items);
    expect(state.pageItems).toHaveLength(48);
    await act(async () => state.setPage(3));
    expect(state.pageItems).toEqual([96, 97, 98, 99]);
  });

  it('a new search or filter starts on page 1', async () => {
    await render(items);
    await act(async () => state.setPage(2));
    await render(items, 'term');
    expect(state.page).toBe(1);
  });

  // Deleting the only item on the last page leaves the page past the end.
  it('stays within the pages left when the list shrinks', async () => {
    await render(items);
    await act(async () => state.setPage(3));
    await render(items.slice(0, 96));
    expect(state.page).toBe(2);
    expect(state.pageItems[0]).toBe(48);
  });
});
