import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import RoleMeta from './RoleMeta';
import { can, roleOf } from '../utils/accessUtils';

describe('RoleMeta', () => {
  it('shows the role as a meta item with the Users icon', () => {
    const html = renderToStaticMarkup(<RoleMeta item={{ access: 'editor' }} />);
    expect(html).toContain('data-slot="meta-item"');
    expect(html).toContain('data-testid="role-meta"');
    expect(html).toContain('lucide-users');
    expect(html).toContain('teamAccess.editor');
    expect(html).not.toContain('data-slot="badge"');
  });

  it('reads the legacy team fields through roleOf', () => {
    const html = renderToStaticMarkup(
      <RoleMeta item={{ ownership: 'team', team_access: null }} />,
    );
    expect(html).toContain('teamAccess.viewer');
  });

  it('renders nothing for the caller’s own item', () => {
    expect(renderToStaticMarkup(<RoleMeta item={{}} />)).toBe('');
  });

  it('renders nothing on a team item: team tiles name who added it instead', () => {
    for (const access of ['admin', 'editor', 'viewer'] as const) {
      const html = renderToStaticMarkup(
        <RoleMeta item={{ origin: 'team', access }} />,
      );
      expect(html).toBe('');
    }
  });

  it('shows the role on an item shared with the caller', () => {
    const html = renderToStaticMarkup(
      <RoleMeta item={{ origin: 'shared', access: 'editor' }} />,
    );
    expect(html).toContain('teamAccess.editor');
  });

  it('renders nothing on the caller’s own item, whatever its access says', () => {
    expect(
      renderToStaticMarkup(
        <RoleMeta item={{ origin: 'own', access: 'owner' }} />,
      ),
    ).toBe('');
  });

  it('never reads admin access as Viewer', () => {
    const html = renderToStaticMarkup(<RoleMeta item={{ access: 'admin' }} />);
    expect(html).not.toContain('teamAccess.viewer');
    expect(html).toContain('workspace.common.roles.admin');
  });
});

describe('accessUtils with team roles', () => {
  it('keeps admin as the role', () => {
    expect(roleOf({ access: 'admin' })).toBe('admin');
  });

  it('gives a stale admin item at least an editor’s actions', () => {
    expect(can({ access: 'admin' }, 'edit')).toBe(true);
    expect(can({ access: 'admin' }, 'delete')).toBe(true);
    expect(can({ access: 'viewer' }, 'delete')).toBe(false);
  });

  it('still prefers the server’s allowed actions', () => {
    expect(can({ access: 'admin', allowed_actions: ['use'] }, 'edit')).toBe(
      false,
    );
  });
});
