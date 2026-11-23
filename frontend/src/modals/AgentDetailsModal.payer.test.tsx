import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

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

// A session token whose subject is u1, the reader.
const TOKEN = `h.${btoa(JSON.stringify({ sub: 'u1' }))}.s`;

const mocks = vi.hoisted(() => ({
  takeOver: vi.fn(),
  dispatch: vi.fn(),
  getAgent: vi.fn(),
  shareAgent: vi.fn(),
  getAgentWebhook: vi.fn(),
  regenerateAgentKey: vi.fn(),
}));

vi.mock('react-redux', () => ({
  useDispatch: () => mocks.dispatch,
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: TOKEN },
      workspace: {
        current: 't1',
        workspaces: [{ id: 't1', kind: 'team', name: 'Operations' }],
      },
    }),
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getAgent: mocks.getAgent,
    shareAgent: mocks.shareAgent,
    getAgentWebhook: mocks.getAgentWebhook,
    regenerateAgentKey: mocks.regenerateAgentKey,
  },
}));
vi.mock('../api/services/payerService', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  default: { takeOverOutsideAccess: mocks.takeOver },
}));
vi.mock('../agents/ApiWriteAllowlist', () => ({ default: () => null }));

vi.mock('../payer/TakeOverModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockTakeOver({
      kind,
      name,
      modalState,
      setModalState,
      onConfirm,
    }: {
      kind: string;
      name: string;
      modalState: string;
      setModalState: (s: string) => void;
      onConfirm: () => Promise<unknown>;
    }) {
      const [failed, setFailed] = useState(false);
      if (modalState !== 'ACTIVE') return null;
      return (
        <div data-testid="take-over" data-kind={kind} data-name={name}>
          {failed ? <p data-testid="take-over-failed" /> : null}
          <button
            type="button"
            data-testid="take-over-confirm"
            onClick={() =>
              onConfirm().then(
                () => setModalState('INACTIVE'),
                () => setFailed(true),
              )
            }
          />
        </div>
      );
    },
  };
});

import type { Agent } from '../agents/types';
import { PayerApiError } from '../api/services/payerService';
import type { OutsideAccess } from '../payer/types';
import AgentDetailsModal from './AgentDetailsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const DANA = { user_id: 'u2', label: 'dana@meridian.example' };
const THIS_YEAR = new Date().getFullYear();

const teamAgent = (outside: Partial<OutsideAccess> | null): Agent =>
  ({
    id: 'a1',
    name: 'Carrier desk',
    status: 'published',
    key: 'abcd...wxyz',
    access: 'admin',
    allowed_actions: ['view', 'edit', 'manage_access_details'],
    workspace: { kind: 'team', team_id: 't1' },
    outside_access:
      outside === null
        ? undefined
        : {
            api_key: true,
            public_link: true,
            webhook: false,
            paid_by: DANA,
            paused_for: null,
            can_take_over: true,
            ...outside,
          },
  }) as Agent;

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
  document.body.innerHTML = '';
  Object.values(mocks).forEach((m) => m.mockReset());
});

const render = async (agent: Agent) => {
  await act(async () => {
    root.render(
      <AgentDetailsModal
        agent={agent}
        mode="edit"
        modalState="ACTIVE"
        setModalState={() => undefined}
      />,
    );
  });
};

const text = () => document.body.textContent ?? '';
const takeOver = () =>
  [...document.querySelectorAll('button')].find(
    (b) => b.textContent === 'payer.common.takeOver.submit',
  );
const confirm = () =>
  act(async () =>
    document
      .querySelector<HTMLButtonElement>('[data-testid="take-over-confirm"]')!
      .click(),
  );

describe('AgentDetailsModal: who pays for outside access', () => {
  it('says who pays on a team agent', async () => {
    await render(teamAgent({ can_take_over: false }));
    expect(text()).toContain('payer.common.paidBy(name=dana@meridian.example)');
    expect(takeOver()).toBeUndefined();
  });

  it('says "Paid by you" to the payer', async () => {
    await render(
      teamAgent({
        paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
        can_take_over: false,
      }),
    );
    expect(text()).toContain('payer.common.paidByYou');
  });

  it('names nobody on a personal agent, and has nothing without the block', async () => {
    await render({
      ...teamAgent({ paid_by: null, can_take_over: false }),
      access: 'owner',
      workspace: { kind: 'personal', team_id: null },
    } as Agent);
    expect(text()).not.toContain('payer.common.paidBy');
    await render(teamAgent(null));
    expect(text()).not.toContain('payer.common.paidBy');
    expect(takeOver()).toBeUndefined();
  });

  it('says nothing about a payer while everything is off', async () => {
    await render(
      teamAgent({ api_key: false, public_link: false, paid_by: null }),
    );
    expect(text()).not.toContain('payer.');
  });

  it('says why outside access is paused, in a warning', async () => {
    await render(
      teamAgent({
        paused_for: {
          reason: 'payer_out_of_allowance',
          until: `${THIS_YEAR}-12-01T00:00:00Z`,
        },
      }),
    );
    const alert = document.querySelector('[data-variant="warning"]');
    expect(alert?.textContent).toContain('payer.access.notice(reason=');
    expect(alert?.textContent).toContain(
      'payer.common.pause.outOfAllowance(name=dana@meridian.example,date=',
    );
    // Take over is the fix, at the end of the notice.
    expect(alert?.contains(takeOver()!)).toBe(true);
  });

  it('names the team the payer left', async () => {
    await render(teamAgent({ paused_for: { reason: 'payer_left' } }));
    expect(text()).toContain(
      'payer.common.pause.payerLeft(name=dana@meridian.example,team=Operations)',
    );
  });

  it("tells a personal agent's owner it is their own allowance", async () => {
    await render({
      ...teamAgent({
        paid_by: null,
        can_take_over: false,
        paused_for: {
          reason: 'payer_out_of_allowance',
          until: `${THIS_YEAR}-12-01T00:00:00Z`,
        },
      }),
      access: 'owner',
      workspace: { kind: 'personal', team_id: null },
    } as Agent);
    expect(text()).toContain('payer.common.pause.outOfAllowanceYou(date=');
    expect(takeOver()).toBeUndefined();
  });

  it('offers Take over only with can_take_over', async () => {
    await render(
      teamAgent({ paused_for: { reason: 'no_payer' }, can_take_over: false }),
    );
    expect(text()).toContain('payer.common.pause.noPayer');
    expect(takeOver()).toBeUndefined();
  });

  it('takes over and shows the outside access the server answered with', async () => {
    mocks.takeOver.mockResolvedValue({
      changed: true,
      outside_access: {
        api_key: true,
        public_link: true,
        webhook: false,
        paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
        paused_for: null,
        can_take_over: false,
      },
    });
    await render(teamAgent({ paused_for: { reason: 'payer_left' } }));
    await act(async () => takeOver()!.click());
    const dialog = document.querySelector('[data-testid="take-over"]');
    expect(dialog?.getAttribute('data-kind')).toBe('outside_access');
    expect(dialog?.getAttribute('data-name')).toBe('Carrier desk');
    await confirm();
    expect(mocks.takeOver).toHaveBeenCalledWith('a1', TOKEN);
    expect(text()).toContain('payer.common.paidByYou');
    expect(text()).not.toContain('payer.access.notice');
    expect(takeOver()).toBeUndefined();
    expect(mocks.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({
          variant: 'success',
          message: 'payer.access.takenOver',
        }),
      }),
    );
  });

  it('keeps the dialog open and the notice on a refusal', async () => {
    mocks.takeOver.mockRejectedValue(
      new PayerApiError(409, 'no', 'no_outside_access'),
    );
    await render(teamAgent({ paused_for: { reason: 'payer_left' } }));
    await act(async () => takeOver()!.click());
    await confirm();
    expect(
      document.querySelector('[data-testid="take-over-failed"]'),
    ).not.toBeNull();
    expect(text()).toContain('payer.access.notice');
    expect(mocks.dispatch).not.toHaveBeenCalled();
  });

  it('reads who pays again after turning something on', async () => {
    mocks.shareAgent.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ shared_token: 'tok-1' }),
    });
    mocks.getAgent.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          outside_access: {
            api_key: true,
            public_link: true,
            webhook: false,
            paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
            paused_for: null,
            can_take_over: false,
          },
        }),
    });
    await render(
      teamAgent({ public_link: false, paused_for: { reason: 'no_payer' } }),
    );
    const generate = [...document.querySelectorAll('button')].find(
      (b) => b.textContent === 'modals.agentDetails.generate',
    )!;
    await act(async () => generate.click());
    expect(mocks.getAgent).toHaveBeenCalledWith('a1', TOKEN);
    expect(text()).toContain('payer.common.paidByYou');
    expect(text()).not.toContain('payer.access.notice');
  });
});
