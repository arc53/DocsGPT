import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

const state = vi.hoisted(() => ({
  preference: {
    roles: [] as string[],
    agents: [],
    sharedAgents: [],
    selectedAgent: null,
  },
  connectors: { enabled: true, connections: [] as { status: string }[] },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import SectionIndexPage from './SectionIndexPage';
import SectionPills from './SectionPills';
import { SETTINGS_SECTION } from './sections';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('the needs-attention dot on phone navigation', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    state.connectors.connections = [{ status: 'reconnect_needed' }];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = (node: React.ReactNode, path = '/settings') =>
    act(async () => {
      root.render(<MemoryRouter initialEntries={[path]}>{node}</MemoryRouter>);
    });

  const dots = () =>
    Array.from(
      container.querySelectorAll('[data-testid="connection-health-dot"]'),
    );

  it('marks the Connectors row of the settings index, before its chevron', async () => {
    await render(<SectionIndexPage section={SETTINGS_SECTION} />);
    expect(dots()).toHaveLength(1);
    const row = dots()[0].closest('a')!;
    expect(row.getAttribute('href')).toBe('/settings/connectors');
    const trailing = Array.from(row.querySelectorAll('svg, [role="img"]'));
    const dotAt = trailing.indexOf(dots()[0]);
    const chevronAt = trailing.findIndex((el) =>
      el.getAttribute('class')?.includes('lucide-chevron-right'),
    );
    expect(dotAt).toBeGreaterThan(-1);
    expect(dotAt).toBeLessThan(chevronAt);
  });

  it('shows no dot while every connection is fine', async () => {
    state.connectors.connections = [{ status: 'connected' }];
    await render(<SectionIndexPage section={SETTINGS_SECTION} />);
    expect(dots()).toHaveLength(0);
  });

  it('marks the Connectors pill', async () => {
    await render(<SectionPills />, '/settings/tools');
    expect(dots()).toHaveLength(1);
    expect(dots()[0].closest('a')!.getAttribute('href')).toBe(
      '/settings/connectors',
    );
  });
});
