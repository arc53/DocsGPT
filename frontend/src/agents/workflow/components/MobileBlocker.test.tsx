import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({ useSelector: () => null }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('@/hooks', () => ({ useMediaQuery: () => ({ isMobile: true }) }));

import type { Agent } from '../../types';
import {
  AGENTS_MANAGE_ROOT,
  agentAnalyticsPath,
  agentEditPath,
  agentLogsPath,
  agentSchedulesPath,
} from '../../paths';
import MobileBlocker from './MobileBlocker';

const workflow = (overrides: Partial<Agent> = {}): Agent =>
  ({
    id: 'wf1',
    name: 'Customer Renewal Desk',
    status: 'published',
    agent_type: 'workflow',
    ...overrides,
  }) as Agent;

const render = (agent: Agent | null, path: string) =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={[path]}>
      <MobileBlocker agent={agent} />
    </MemoryRouter>,
  );

describe('MobileBlocker', () => {
  // The builder has no phone layout; the way back mustn't need the sidebar.
  it('links back to the agent list', () => {
    const html = render(null, `${AGENTS_MANAGE_ROOT}/workflow/new`);
    expect(html).toMatch(
      new RegExp(
        `<a[^>]*href="${AGENTS_MANAGE_ROOT}"[^>]*>.*agents\\.title</a>`,
      ),
    );
    expect(html).toContain('agents.workflow.mobileBlocker.title');
    // The shared empty state with the monitor icon, not a one-off tile.
    expect(html).toContain('data-slot="empty-state"');
    expect(html).toContain('lucide-monitor');
    // Nothing else titles a new workflow's page.
    expect(html).toMatch(
      /<h1[^>]*>agents\.workflow\.mobileBlocker\.title<\/h1>/,
    );
  });

  it("gives a saved workflow its agent page's header and tabs", () => {
    const html = render(workflow(), agentEditPath('wf1', true));
    expect(html).toMatch(/<h1[^>]*>agents\.pageHeader\.tabs\.overview<\/h1>/);
    expect(html).toContain('Customer Renewal Desk');
    expect(html).toContain('agents.form.status.published');
    expect(html).toContain(`href="${agentLogsPath('wf1')}"`);
    expect(html).toContain(`href="${agentSchedulesPath('wf1')}"`);
    expect(html).toContain('agents.workflow.mobileBlocker.title');
  });

  // The same tabs, in the same order, as the agent sidebar; Overview is
  // this page, so it has no link.
  it("links the agent's other pages in the sidebar's order", () => {
    const html = render(workflow(), agentEditPath('wf1', true));
    const hrefs = Array.from(html.matchAll(/<a[^>]*href="([^"]+)"/g))
      .map(([, href]) => href)
      .filter((href) => href !== AGENTS_MANAGE_ROOT);
    expect(hrefs).toEqual([
      agentSchedulesPath('wf1'),
      agentAnalyticsPath('wf1'),
      agentLogsPath('wf1'),
    ]);
    expect(html).toContain('lucide-chart-no-axes-column');
  });

  // Logs and Schedules exist only once published, like the builder's tabs.
  it('leaves the tab links off a draft', () => {
    const html = render(
      workflow({ status: 'draft' }),
      agentEditPath('wf1', true),
    );
    expect(html).toContain('agents.card.draft');
    expect(html).not.toContain(`href="${agentLogsPath('wf1')}"`);
    expect(html).not.toContain(`href="${agentSchedulesPath('wf1')}"`);
  });

  it('shows only the tabs the role allows', () => {
    const html = render(
      workflow({ access: 'viewer', allowed_actions: ['view', 'view_logs'] }),
      agentEditPath('wf1', true),
    );
    expect(html).toContain(`href="${agentLogsPath('wf1')}"`);
    expect(html).toContain(`href="${agentAnalyticsPath('wf1')}"`);
    expect(html).not.toContain(`href="${agentSchedulesPath('wf1')}"`);
  });

  // A saved workflow's page is loading: neither layout yet, so a phone
  // doesn't flash the new-workflow screen first.
  it('shows a spinner while the saved workflow loads', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={[agentEditPath('wf1', true)]}>
        <MobileBlocker agent={null} loading />
      </MemoryRouter>,
    );
    expect(html).toContain('data-slot="loading-state"');
    expect(html).not.toContain('agents.workflow.mobileBlocker.title');
    expect(html).not.toContain(`href="${AGENTS_MANAGE_ROOT}"`);
  });
});
