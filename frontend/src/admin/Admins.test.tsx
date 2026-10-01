import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
}));
vi.mock('../api/services/adminService', () => ({
  default: {
    getAdmins: () =>
      Promise.resolve({ json: async () => ({ success: true, admins: [] }) }),
  },
}));

import Admins from './Admins';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Admins', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Admins />));
    for (let i = 0; i < 3; i += 1) await act(async () => Promise.resolve());
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
});
