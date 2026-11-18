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

// The team's outside policy, set per test.
const team = vi.hoisted(() => ({ policy: 'admins' as string }));

vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: null },
      workspace: {
        current: 't1',
        workspaces: [
          {
            id: 't1',
            kind: 'team',
            name: 'Operations',
            outside_policy: team.policy,
          },
        ],
      },
    }),
}));
vi.mock('../api/services/userService', () => ({ default: {} }));
vi.mock('../agents/ApiWriteAllowlist', () => ({ default: () => null }));

import type { Agent } from '../agents/types';
import AgentDetailsModal from './AgentDetailsModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// Published while the team was locked: no key, no link, no webhook.
const agent = {
  id: 'a1',
  name: 'Carrier desk',
  status: 'published',
  access: 'admin',
  allowed_actions: ['view', 'edit'],
  workspace: { kind: 'team', team_id: 't1' },
} as Agent;

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
  team.policy = 'admins';
});

const render = async (shown: Agent = agent) => {
  await act(async () => {
    root.render(
      <AgentDetailsModal
        agent={shown}
        mode="edit"
        modalState="ACTIVE"
        setModalState={() => undefined}
      />,
    );
  });
};

const generateButtons = () =>
  [...document.querySelectorAll('button')].filter(
    (b) => b.textContent === 'modals.agentDetails.generate',
  );

describe('AgentDetailsModal in a locked team', () => {
  it('says the team is locked and offers nothing to turn on', async () => {
    team.policy = 'locked';
    await render();
    const note = document.querySelector('[data-slot="alert"]');
    expect(note?.getAttribute('data-variant')).toBe('info');
    expect(note?.textContent).toContain(
      'modals.agentDetails.teamLocked(team=Operations)',
    );
    expect(generateButtons()).toHaveLength(0);
  });

  it('offers the links again once the team is unlocked', async () => {
    await render();
    expect(document.body.textContent).not.toContain(
      'modals.agentDetails.teamLocked',
    );
    expect(generateButtons().length).toBeGreaterThan(0);
  });

  it('leaves the paused notice to say it once outside access is on', async () => {
    team.policy = 'locked';
    await render({
      ...agent,
      key: 'abcd...wxyz',
      outside_access: {
        api_key: true,
        public_link: false,
        webhook: false,
        paid_by: null,
        paused_for: { reason: 'team_locked' },
        can_take_over: false,
      },
    } as Agent);
    expect(document.body.textContent).toContain(
      'payer.common.pause.teamLocked',
    );
    expect(document.body.textContent).not.toContain(
      'modals.agentDetails.teamLocked',
    );
    // A paused key isn't reset while the team is locked.
    expect(
      [...document.querySelectorAll('button')].some(
        (b) => b.textContent === 'modals.agentDetails.resetKey',
      ),
    ).toBe(false);
  });
});
