import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./SidebarLevelProvider', () => ({
  useSidebarLevel: () => ({ goToLevel: vi.fn() }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import SectionRail from './SectionRail';
import { SETTINGS_SECTION, getSectionItems } from './sections';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SectionRail', () => {
  let container: HTMLDivElement;
  let root: Root;
  const items = getSectionItems(SETTINGS_SECTION, { isAdmin: false });

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <MemoryRouter>
          <TooltipProvider>
            <SectionRail
              section={SETTINGS_SECTION}
              activeItemKey={items[0].key}
              isAdmin={false}
              onBack={() => undefined}
              backLabel="back"
            />
          </TooltipProvider>
        </MemoryRouter>,
      );
    });
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
});
