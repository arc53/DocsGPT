import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AgentPageHeader from './AgentPageHeader';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentPageHeader sub-nav', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('renders the tabs as underline tab buttons, marking the current page', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <AgentPageHeader
            agentId="a1"
            agentName="Renewals"
            currentPage="logs"
          />
        </MemoryRouter>,
      );
    });
    const nav = container.querySelector(
      'nav[aria-label="agents.pageHeader.subnavAriaLabel"]',
    );
    const tabs = Array.from(nav?.children ?? []);
    expect(tabs).toHaveLength(3);
    for (const tab of tabs) {
      expect(tab.getAttribute('data-variant')).toBe('tab');
      expect(tab.getAttribute('data-size')).toBe('inline');
    }
    const current = tabs[1];
    expect(current.tagName).toBe('SPAN');
    expect(current.getAttribute('aria-current')).toBe('page');
    expect(current.getAttribute('data-active')).toBe('true');
    expect(tabs[0].tagName).toBe('A');
    expect(tabs[0].getAttribute('data-active')).not.toBe('true');
  });
});
