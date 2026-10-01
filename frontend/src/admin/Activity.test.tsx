import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));

const empty = () =>
  Promise.resolve({
    ok: true,
    json: async () => ({ success: true, activity: [], total: 0, events: [] }),
  });
vi.mock('../api/services/adminService', () => ({
  default: {
    getActivity: () => empty(),
    getActivityEvents: () => empty(),
    exportActivity: vi.fn(),
  },
}));

import Activity from './Activity';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Activity toolbar', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Activity />
        </MemoryRouter>,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('draws both filters as field pills', () => {
    const filters = Array.from(
      container.querySelectorAll('[data-slot="multi-select-trigger"]'),
    );
    expect(filters).toHaveLength(2);
    for (const filter of filters) {
      expect(filter.getAttribute('data-size')).toBe('field');
      expect(filter.getAttribute('data-shape')).toBe('pill');
    }
  });

  it('draws the exports as outline field pills', () => {
    const exports = Array.from(container.querySelectorAll('button')).filter(
      (b) => ['CSV', 'NDJSON'].includes(b.textContent?.trim() ?? ''),
    );
    expect(exports).toHaveLength(2);
    for (const button of exports) {
      expect(button.getAttribute('data-variant')).toBe('outline');
      expect(button.getAttribute('data-size')).toBe('field');
      expect(button.getAttribute('data-shape')).toBe('pill');
    }
  });

  it('says "No activity." in a small text-only EmptyState', () => {
    const empty = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"]',
    );
    expect(empty?.dataset.size).toBe('sm');
    expect(empty?.querySelector('svg')).toBeNull();
    expect(empty?.textContent).toBe('No activity.');
  });
});
