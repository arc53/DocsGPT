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

  it('renders the tabs as NavTabs at full size, the overview marked current', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <AgentPageHeader
            agentId="a1"
            agentName="Renewals"
            onNameClick={vi.fn()}
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
      expect(tab.getAttribute('data-slot')).toBe('nav-tab');
      expect(tab.className).toContain('h-9');
      expect(tab.className).toContain('px-4');
    }
    // Tabs sit edge to edge: the nav has no gap.
    expect(nav?.className).not.toMatch(/\bgap-/);
    const current = tabs[0];
    expect(current.tagName).toBe('SPAN');
    expect(current.getAttribute('aria-current')).toBe('page');
    expect(tabs[1].tagName).toBe('A');
    expect(tabs[1].getAttribute('aria-current')).toBeNull();
  });

  it('shows only the tabs the role allows', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <AgentPageHeader
            agentId="a1"
            agentName="Renewals"
            onNameClick={vi.fn()}
            access={{
              access: 'editor',
              allowed_actions: ['view', 'view_logs'],
            }}
          />
        </MemoryRouter>,
      );
    });
    const nav = container.querySelector(
      'nav[aria-label="agents.pageHeader.subnavAriaLabel"]',
    );
    expect(Array.from(nav?.children ?? []).map((t) => t.textContent)).toEqual([
      'agents.pageHeader.tabs.overview',
      'agents.pageHeader.tabs.logs',
    ]);
  });

  it('makes the current crumb a button with the avatar and a chevron that opens the details', () => {
    const onNameClick = vi.fn();
    act(() => {
      root.render(
        <MemoryRouter>
          <AgentPageHeader
            agentId="a1"
            agentName="Helpdesk Triage"
            onNameClick={onNameClick}
            status={<span data-testid="status">Published</span>}
          />
        </MemoryRouter>,
      );
    });
    const crumb = container.querySelector(
      'button[aria-haspopup="dialog"]',
    ) as HTMLButtonElement;
    expect(crumb).not.toBeNull();
    expect(crumb.getAttribute('data-variant')).toBe('ghost');
    expect(crumb.getAttribute('data-size')).toBe('sm');
    expect(crumb.querySelector('img')).not.toBeNull();
    expect(crumb.querySelector('.lucide-chevron-down')).not.toBeNull();
    expect(crumb.textContent).toContain('Helpdesk Triage');
    // The name is the current crumb, so it takes BreadcrumbPage's 32ch cap.
    expect(
      crumb.querySelector('span[title="Helpdesk Triage"]')?.className,
    ).toContain('max-w-[32ch]');
    expect(container.querySelector('[data-testid="status"]')).not.toBeNull();
    act(() => crumb.click());
    expect(onNameClick).toHaveBeenCalledTimes(1);
  });

  it('hides the tabs for a workflow that has no id yet', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <AgentPageHeader agentName="New workflow" onNameClick={vi.fn()} />
        </MemoryRouter>,
      );
    });
    expect(
      container.querySelector(
        'nav[aria-label="agents.pageHeader.subnavAriaLabel"]',
      ),
    ).toBeNull();
  });
});
