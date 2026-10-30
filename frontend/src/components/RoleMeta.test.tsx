import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import RoleMeta from './RoleMeta';

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
});
