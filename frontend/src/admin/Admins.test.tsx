import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));
const admins: { current: Record<string, unknown>[] } = { current: [] };
vi.mock('../api/services/adminService', () => ({
  default: {
    getAdmins: () =>
      Promise.resolve({
        json: async () => ({ success: true, admins: admins.current }),
      }),
  },
}));

import Admins from './Admins';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Admins', () => {
  let container: HTMLDivElement;
  let root: Root;

  const render = async () => {
    await act(async () => root.render(<Admins />));
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
  };

  beforeEach(async () => {
    admins.current = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await render();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('says "No admins." in a small text-only EmptyState', () => {
    const empty = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"]',
    );
    expect(empty?.dataset.size).toBe('sm');
    expect(empty?.querySelector('svg')).toBeNull();
    expect(empty?.textContent).toBe('No admins.');
  });

  it('names an admin by email over the user id', async () => {
    admins.current = [
      { user_id: 'sub-1', email: 'boss@example.com', sources: ['manual'] },
      { user_id: 'sub-2', email: null, sources: ['manual'] },
    ];
    act(() => root.unmount());
    root = createRoot(container);
    await render();
    const cells = Array.from(
      container.querySelectorAll('tbody tr td:first-child'),
    ).map((td) => td.textContent);
    expect(cells).toEqual(['boss@example.comsub-1', 'sub-2']);
  });
});
