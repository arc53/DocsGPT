import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const params = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${params})`;
    },
    i18n: { language: 'en' },
  }),
}));

const mocks = vi.hoisted(() => ({ getAgent: vi.fn() }));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: 'tok' },
      workspace: {
        current: 't1',
        workspaces: [{ id: 't1', kind: 'team', name: 'Operations' }],
      },
    }),
}));
vi.mock('../api/services/userService', () => ({
  default: { getAgent: mocks.getAgent },
}));

import AgentPageToolbar from './components/AgentPageToolbar';
import OwnerInactiveNotice, {
  AgentNoticeContext,
  OutsideAccessNotice,
  OwnerInactiveBadge,
  rememberOutsideAccess,
} from './OwnerInactiveNotice';
import type { OutsideAccess } from '../payer/types';
import type { Agent } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const agent = (ownerInactive: boolean) =>
  ({ id: 'a1', name: 'Desk', owner_inactive: ownerInactive }) as Agent & {
    owner_inactive: boolean;
  };

describe("an agent whose owner's account is deactivated", () => {
  it('says outside access is paused', () => {
    const html = renderToStaticMarkup(
      <OwnerInactiveNotice agent={agent(true)} />,
    );
    expect(html).toContain('workspace.notices.ownerInactive');
    expect(html).toContain('role="note"');
  });

  it('says nothing for an active owner', () => {
    expect(
      renderToStaticMarkup(<OwnerInactiveNotice agent={agent(false)} />),
    ).toBe('');
  });

  it("shows on an agent page's toolbar from the opened agent", () => {
    const html = renderToStaticMarkup(
      <AgentNoticeContext.Provider value={agent(true)}>
        <AgentPageToolbar name="Desk" />
      </AgentNoticeContext.Provider>,
    );
    expect(html).toContain('workspace.notices.ownerInactive');
  });

  it("doesn't show on a toolbar outside an agent's pages", () => {
    expect(
      renderToStaticMarkup(<AgentPageToolbar name="Desk" />),
    ).not.toContain('workspace.notices.ownerInactive');
  });

  it("the builder's header carries a short badge", () => {
    const html = renderToStaticMarkup(
      <AgentNoticeContext.Provider value={agent(true)}>
        <OwnerInactiveBadge />
      </AgentNoticeContext.Provider>,
    );
    expect(html).toContain('workspace.notices.ownerInactiveShort');
  });
});

const DANA = { user_id: 'u2', label: 'dana@meridian.example' };
const THIS_YEAR = new Date().getFullYear();

const withAccess = (
  id: string,
  outside: Partial<OutsideAccess> | undefined,
  fields: Partial<Agent> = {},
): Agent =>
  ({
    id,
    name: 'Carrier desk',
    status: 'published',
    access: 'admin',
    allowed_actions: ['view', 'edit', 'manage_access_details'],
    workspace: { kind: 'team', team_id: 't1' },
    outside_access:
      outside === undefined
        ? undefined
        : {
            api_key: true,
            public_link: false,
            webhook: false,
            paid_by: DANA,
            paused_for: null,
            can_take_over: true,
            ...outside,
          },
    ...fields,
  }) as Agent;

describe('why outside access is paused', () => {
  it('names an out-of-allowance payer and the reset date', () => {
    const html = renderToStaticMarkup(
      <OutsideAccessNotice
        agent={withAccess('p1', {
          paused_for: {
            reason: 'payer_out_of_allowance',
            until: `${THIS_YEAR}-12-01T00:00:00Z`,
          },
        })}
      />,
    );
    expect(html).toContain('payer.access.notice(reason=');
    expect(html).toContain(
      'payer.common.pause.outOfAllowance(name=dana@meridian.example,date=',
    );
    expect(html).toContain('role="note"');
    expect(html).toContain('data-variant="warning"');
  });

  it('says the payer left the team, naming it', () => {
    const html = renderToStaticMarkup(
      <OutsideAccessNotice
        agent={withAccess('p2', { paused_for: { reason: 'payer_left' } })}
      />,
    );
    expect(html).toContain(
      'payer.common.pause.payerLeft(name=dana@meridian.example,team=Operations)',
    );
  });

  it('says nobody pays', () => {
    const html = renderToStaticMarkup(
      <OutsideAccessNotice
        agent={withAccess('p3', {
          paid_by: null,
          paused_for: { reason: 'no_payer' },
        })}
      />,
    );
    expect(html).toContain('payer.common.pause.noPayer');
  });

  it('keeps the owner-inactive sentence for that reason', () => {
    const html = renderToStaticMarkup(
      <OutsideAccessNotice
        agent={withAccess('p4', { paused_for: { reason: 'owner_inactive' } })}
      />,
    );
    expect(html).toContain('workspace.notices.ownerInactive');
    expect(html).not.toContain('payer.access.notice');
  });

  it('says nothing while it runs', () => {
    expect(
      renderToStaticMarkup(
        <OutsideAccessNotice agent={withAccess('p5', {})} />,
      ),
    ).toBe('');
  });

  it("the builder's badge shows for a payer pause too", () => {
    const html = renderToStaticMarkup(
      <AgentNoticeContext.Provider
        value={withAccess('p6', { paused_for: { reason: 'no_payer' } })}
      >
        <OwnerInactiveBadge />
      </AgentNoticeContext.Provider>,
    );
    expect(html).toContain('workspace.notices.ownerInactiveShort');
    expect(html).toContain('payer.common.pause.noPayer');
  });
});

describe('an opened agent read from the list', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    mocks.getAgent.mockReset();
  });

  const mount = async (opened: Agent) => {
    await act(async () => {
      root.render(
        <AgentNoticeContext.Provider value={opened}>
          <OutsideAccessNotice />
        </AgentNoticeContext.Provider>,
      );
    });
  };

  it("reads the agent once for an admin, since the list doesn't carry who pays", async () => {
    mocks.getAgent.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          outside_access: {
            api_key: true,
            public_link: false,
            webhook: false,
            paid_by: DANA,
            paused_for: { reason: 'payer_left', until: null },
            can_take_over: true,
          },
        }),
    });
    await mount(withAccess('l1', undefined));
    expect(mocks.getAgent).toHaveBeenCalledWith('l1', 'tok');
    expect(container.textContent).toContain('payer.common.pause.payerLeft');
  });

  it('reads nothing for a reader who may not manage access, or a draft', async () => {
    await mount(
      withAccess('l2', undefined, {
        access: 'editor',
        allowed_actions: ['view', 'edit'],
      }),
    );
    await mount(withAccess('l3', undefined, { status: 'draft' }));
    expect(mocks.getAgent).not.toHaveBeenCalled();
    expect(container.textContent).toBe('');
  });

  it('reads nothing when the agent carries its outside access', async () => {
    await mount(withAccess('l4', { paused_for: { reason: 'no_payer' } }));
    expect(mocks.getAgent).not.toHaveBeenCalled();
    expect(container.textContent).toContain('payer.common.pause.noPayer');
  });

  it('clears once someone takes it over on the same page', async () => {
    await mount(withAccess('l5', { paused_for: { reason: 'payer_left' } }));
    expect(container.textContent).toContain('payer.access.notice');
    await act(async () =>
      rememberOutsideAccess('l5', {
        api_key: true,
        public_link: false,
        webhook: false,
        paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
        paused_for: null,
        can_take_over: false,
      }),
    );
    expect(container.textContent).toBe('');
  });

  const takenOver: OutsideAccess = {
    api_key: true,
    public_link: false,
    webhook: false,
    paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
    paused_for: null,
    can_take_over: false,
  };

  it('stays cleared after a take over while the page keeps the record it had', async () => {
    vi.useFakeTimers();
    try {
      const opened = withAccess('l6', { paused_for: { reason: 'payer_left' } });
      await mount(opened);
      await act(async () => rememberOutsideAccess('l6', takenOver));
      expect(container.textContent).toBe('');
      // Minutes later the page re-renders with the record read before it.
      vi.advanceTimersByTime(5 * 60_000);
      await mount({ ...opened });
      expect(container.textContent).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });

  it('follows a record of the agent read after the take over', async () => {
    vi.useFakeTimers();
    try {
      mocks.getAgent.mockReturnValue(new Promise(() => {}));
      await mount(withAccess('l7', undefined));
      await act(async () => rememberOutsideAccess('l7', takenOver));
      vi.advanceTimersByTime(60_000);
      await mount(withAccess('l7', { paused_for: { reason: 'no_payer' } }));
      expect(container.textContent).toContain('payer.common.pause.noPayer');
    } finally {
      vi.useRealTimers();
    }
  });
});
