import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));

const feed: { current: Record<string, unknown>[] } = { current: [] };
const empty = () =>
  Promise.resolve({
    ok: true,
    json: async () => ({
      success: true,
      activity: feed.current,
      total: feed.current.length,
      events: [],
    }),
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

  const render = async () => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <Activity />
        </MemoryRouter>,
      );
    });
  };

  beforeEach(async () => {
    feed.current = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await render();
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

  it('names the actor by email over the id, the affected user by id', async () => {
    feed.current = [
      {
        feed: 'auth',
        id: '1',
        event: 'role_granted',
        category: 'access',
        actor_id: 'sub-admin',
        actor_email: 'admin@example.com',
        target_id: 'sub-user',
        target_email: null,
        ip: null,
        user_agent: null,
        outcome: null,
        detail: {},
        created_at: '2026-01-01T00:00:00Z',
      },
    ];
    await act(async () => root.unmount());
    root = createRoot(container);
    await render();
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
    const cells = Array.from(container.querySelectorAll('tbody tr td'));
    const texts = cells.map((td) => td.textContent);
    expect(texts).toContain('admin@example.comsub-admin');
    expect(texts).toContain('sub-user');
  });
});
