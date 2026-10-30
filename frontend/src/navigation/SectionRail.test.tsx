import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

const state = vi.hoisted(() => ({
  preference: { analyticsEnabled: true },
  connectors: { enabled: true },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./SidebarLevelProvider', () => ({
  useSidebarLevel: () => ({ goToLevel: vi.fn() }),
}));

import { agentInsightsPath, agentLogsPath } from '@/agents/paths';
import { TooltipProvider } from '@/components/ui/tooltip';

import SectionRail from './SectionRail';
import {
  SETTINGS_SECTION,
  buildAgentSection,
  getSectionItems,
  type Section,
} from './sections';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SectionRail', () => {
  let container: HTMLDivElement;
  let root: Root;
  const items = getSectionItems(SETTINGS_SECTION, { isAdmin: false });

  const render = (section: Section = SETTINGS_SECTION) =>
    act(() => {
      root.render(
        <MemoryRouter>
          <TooltipProvider>
            <SectionRail
              section={section}
              activeItemKey={items[0].key}
              isAdmin={false}
              onBack={() => undefined}
              backLabel="back"
            />
          </TooltipProvider>
        </MemoryRouter>,
      );
    });

  beforeEach(() => {
    state.preference.analyticsEnabled = true;
    state.connectors.enabled = true;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    render();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const links = () =>
    Array.from(container.querySelectorAll<HTMLAnchorElement>('a'));

  it('draws the token focus ring on every rail link', () => {
    expect(links()).toHaveLength(items.length);
    for (const link of links()) {
      expect(link.className).toContain('focus-visible:ring-3');
      expect(link.className).toContain('outline-none');
    }
  });

  // Like the Back IconButton above them: a tooltip, not a native title.
  it('names each icon link with a tooltip instead of a title', () => {
    for (const link of links()) {
      expect(link.hasAttribute('title')).toBe(false);
      expect(link.getAttribute('aria-label')).toBeTruthy();
      expect(link.dataset.slot).toBe('tooltip-trigger');
    }
    expect(links()[0].getAttribute('aria-current')).toBe('page');
  });

  const hrefs = () => links().map((link) => link.getAttribute('href'));

  // The rail lists what the expanded nav lists: a page the server has
  // switched off is not a destination, or clicking it bounces.
  it('drops Insights and Connectors while the server has them off', () => {
    expect(hrefs()).toContain('/settings/insights');
    expect(hrefs()).toContain('/settings/connectors');

    state.preference.analyticsEnabled = false;
    state.connectors.enabled = false;
    render();
    expect(hrefs()).not.toContain('/settings/insights');
    expect(hrefs()).not.toContain('/settings/connectors');
    expect(hrefs()).toContain('/settings/logs');
  });

  it("drops an agent's Insights tab while analytics is off", () => {
    const agent = buildAgentSection('a1', 'Docs', false);
    render(agent);
    expect(hrefs()).toContain(agentInsightsPath('a1'));

    state.preference.analyticsEnabled = false;
    render(agent);
    expect(hrefs()).not.toContain(agentInsightsPath('a1'));
    expect(hrefs()).toContain(agentLogsPath('a1'));
  });
});
