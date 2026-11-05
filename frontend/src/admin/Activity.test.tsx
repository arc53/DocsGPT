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

  const row = (id: string, actorId: string | null) => ({
    feed: 'auth',
    id,
    event: 'role_granted',
    category: 'access',
    actor_id: actorId,
    actor_email: actorId ? `${actorId}@example.com` : null,
    target_id: null,
    target_email: null,
    ip: null,
    user_agent: null,
    outcome: null,
    detail: {},
    created_at: '2026-01-01T00:00:00Z',
  });

  const actorCells = async () => {
    await act(async () => root.unmount());
    root = createRoot(container);
    await render();
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
    // Data rows have the expand button; detail rows don't. Actor is column 4.
    return Array.from(container.querySelectorAll('tbody tr'))
      .filter((tr) => tr.querySelector('button'))
      .map((tr) => tr.querySelectorAll('td')[3] as HTMLElement);
  };

  it('still names an actor repeated from the row above, muted', async () => {
    feed.current = [row('1', 'dana'), row('2', 'dana'), row('3', 'lena')];
    const cells = await actorCells();
    expect(cells.map((td) => td.textContent)).toEqual([
      'dana@example.comdana',
      'dana@example.comdana',
      'lena@example.comlena',
    ]);
    expect(cells[0].className).not.toContain('text-muted-foreground');
    expect(cells[1].className).toContain('text-muted-foreground');
    expect(cells[2].className).not.toContain('text-muted-foreground');
  });

  it('shows a dash for each row without an actor', async () => {
    feed.current = [row('1', null), row('2', null)];
    const cells = await actorCells();
    expect(cells.map((td) => td.textContent)).toEqual(['—', '—']);
  });
});
