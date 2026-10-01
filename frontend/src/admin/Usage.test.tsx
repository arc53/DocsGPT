import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const getUsage = vi.fn();
vi.mock('../api/services/adminService', () => ({
  default: { getUsage: (...a: unknown[]) => getUsage(...a) },
}));
// Chart.js needs a canvas; the toolbar is what's under test.
vi.mock('./UsageChart', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./UsageChart')>()),
  default: () => null,
}));

import { prefSlice } from '../preferences/preferenceSlice';
import Usage from './Usage';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Usage toolbar', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getUsage.mockReset().mockResolvedValue({
      json: async () => ({ success: true, series: [], top_users: [] }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('draws the group-by select as a pill beside the pill toggles', async () => {
    const store = configureStore({
      reducer: { preference: prefSlice.reducer },
    });
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Usage />
        </Provider>,
      ),
    );
    for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
    const trigger = container.querySelector<HTMLElement>(
      '[data-slot="select-trigger"]',
    );
    expect(trigger).not.toBeNull();
    expect(trigger?.dataset.shape).toBe('pill');
  });

  it('shows no top users as a small text-only EmptyState', async () => {
    const store = configureStore({
      reducer: { preference: prefSlice.reducer },
    });
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Usage />
        </Provider>,
      ),
    );
    for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
    const empty = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="empty-state"]'),
    ).find((el) => el.textContent === 'No usage.');
    expect(empty?.dataset.size).toBe('sm');
    expect(empty?.querySelector('svg')).toBeNull();
  });
});
