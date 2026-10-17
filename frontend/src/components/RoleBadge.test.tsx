import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import RoleBadge from './RoleBadge';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('RoleBadge', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('shows the role as a neutral Badge with the Users icon first', async () => {
    await act(async () =>
      root.render(<RoleBadge item={{ access: 'editor' }} />),
    );
    const badge = container.querySelector<HTMLElement>('[data-slot="badge"]');
    expect(badge?.dataset.variant ?? badge?.className).toMatch(/neutral|muted/);
    const icon = badge?.firstElementChild;
    expect(icon?.getAttribute('class')).toContain('lucide-users');
    expect(icon?.getAttribute('class')).not.toContain('size-3');
    expect(badge?.textContent).toBe('teamAccess.editor');
  });

  it('reads the legacy team fields through roleOf', async () => {
    await act(async () =>
      root.render(
        <RoleBadge item={{ ownership: 'team', team_access: null }} />,
      ),
    );
    expect(container.textContent).toBe('teamAccess.viewer');
  });

  it('renders nothing for the caller’s own item', async () => {
    await act(async () => root.render(<RoleBadge item={{}} />));
    expect(container.innerHTML).toBe('');
  });
});
