import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { shownFilters, useUrlFilter } from './useUrlFilter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const STATES = ['all', 'connected', 'disconnected'] as const;
type State = (typeof STATES)[number];

describe('useUrlFilter', () => {
  let container: HTMLDivElement;
  let root: Root;
  let state: [State, (value: State) => void];
  let search = '';
  let navigationType = '';

  function Probe({ clears }: { clears?: string[] }) {
    state = useUrlFilter(STATES, { clears });
    search = useLocation().search;
    navigationType = useNavigationType();
    return null;
  }

  const render = async (entry: string, clears?: string[]) => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[entry]}>
          <Probe clears={clears} />
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

  it('reads ?filter=, and the first value when absent or unknown', async () => {
    await render('/settings/connectors?filter=connected');
    expect(state[0]).toBe('connected');
    await act(async () => root.unmount());
    root = createRoot(container);
    await render('/settings/connectors?filter=bogus');
    expect(state[0]).toBe('all');
    await act(async () => root.unmount());
    root = createRoot(container);
    await render('/settings/connectors');
    expect(state[0]).toBe('all');
  });

  it('writes the value, keeps other params and leaves "all" out', async () => {
    await render('/settings/connectors?capability=sync');
    await act(async () => state[1]('disconnected'));
    expect(state[0]).toBe('disconnected');
    expect(search).toBe('?capability=sync&filter=disconnected');
    await act(async () => state[1]('all'));
    expect(state[0]).toBe('all');
    expect(search).toBe('?capability=sync');
  });

  it('replaces the history entry instead of pushing one', async () => {
    await render('/settings/connectors');
    await act(async () => state[1]('connected'));
    expect(navigationType).toBe('REPLACE');
  });

  it('drops the params named in `clears` (a page) when the filter changes', async () => {
    await render('/settings/knowledge?page=3&q=x', ['page']);
    await act(async () => state[1]('connected'));
    expect(search).toBe('?q=x&filter=connected');
  });

  it('reads another param when named', async () => {
    let usage = '';
    function Usage() {
      [usage] = useUrlFilter(['all', 'mine'] as const, { name: 'usage' });
      return null;
    }
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/settings/tools?filter=x&usage=mine']}>
          <Usage />
        </MemoryRouter>,
      );
    });
    expect(usage).toBe('mine');
  });
});

describe('shownFilters', () => {
  const counts: Record<State, number> = {
    all: 4,
    connected: 4,
    disconnected: 0,
  };

  it('hides an item whose count is 0', () => {
    expect(shownFilters(STATES, 'all', counts)).toEqual(['all', 'connected']);
  });

  it('keeps the selected item even at 0', () => {
    expect(shownFilters(STATES, 'disconnected', counts)).toEqual([
      'all',
      'connected',
      'disconnected',
    ]);
  });

  it('returns nothing when only All would remain', () => {
    expect(
      shownFilters(STATES, 'all', { all: 3, connected: 0, disconnected: 0 }),
    ).toEqual([]);
  });

  it('keeps All at 0 (an empty list still has its All)', () => {
    expect(
      shownFilters(STATES, 'connected', {
        all: 0,
        connected: 0,
        disconnected: 0,
      }),
    ).toEqual(['all', 'connected']);
  });
});
