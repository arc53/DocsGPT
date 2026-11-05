import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({ useSelector: () => null }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@/hooks', () => ({ useMediaQuery: () => ({ isMobile: false }) }));

import SectionShell from './SectionShell';

describe('SectionShell', () => {
  it('draws a title override in place of the section title', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={['/agents/manage/new']}>
        <SectionShell title="New agent">
          <p>body</p>
        </SectionShell>
      </MemoryRouter>,
    );
    expect(html).toMatch(/<h1[^>]*>New agent<\/h1>/);
    expect(html).toContain('body');
  });
});
