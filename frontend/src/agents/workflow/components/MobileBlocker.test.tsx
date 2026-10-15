import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({ useSelector: () => null }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { AGENTS_MANAGE_ROOT } from '../../paths';
import MobileBlocker from './MobileBlocker';

describe('MobileBlocker', () => {
  // The builder has no phone layout; the way back mustn't need the sidebar.
  it('links back to the agent list', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/agents/manage/workflow/new']}>
        <MobileBlocker />
      </MemoryRouter>,
    );
    expect(html).toMatch(
      new RegExp(
        `<a[^>]*href="${AGENTS_MANAGE_ROOT}"[^>]*>.*agents\\.title</a>`,
      ),
    );
    expect(html).toContain('agents.workflow.mobileBlocker.title');
  });
});
