import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mocks = vi.hoisted(() => ({
  dispatch: vi.fn(),
  goToLevel: vi.fn(),
  deleteAgent: vi.fn(),
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: null, agents: [] } }),
  useDispatch: () => mocks.dispatch,
}));

vi.mock('../api/services/userService', () => ({
  default: { deleteAgent: mocks.deleteAgent },
}));

vi.mock('../navigation/SidebarLevelProvider', () => ({
  useSidebarLevel: () => ({ goToLevel: mocks.goToLevel }),
}));

vi.mock('../modals/MoveToFolderModal', () => ({ default: () => null }));
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({
  default: ({
    modalState,
    handleSubmit,
  }: {
    modalState: string;
    handleSubmit: () => void;
  }) =>
    modalState === 'ACTIVE' ? (
      <button type="button" data-testid="confirm" onClick={handleSubmit} />
    ) : null,
}));

import AgentCard from './AgentCard';
import type { Agent } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const OWNER_ACTIONS = [
  'delete',
  'edit',
  'edit_policy',
  'export',
  'manage_access_details',
  'manage_schedules',
  'manage_settings',
  'move_folder',
  'pin',
  'publish',
  'share',
  'use',
  'view',
  'view_logs',
];
const EDITOR_ACTIONS = [
  'edit',
  'edit_policy',
  'export',
  'manage_access_details',
  'manage_schedules',
  'pin',
  'publish',
  'use',
  'view',
  'view_logs',
];
const VIEWER_ACTIONS = ['pin', 'use'];

const agentWith = (
  access: 'owner' | 'editor' | 'viewer',
  allowed: string[],
): Agent =>
  ({
    id: 'a1',
    name: 'Deal Desk',
    description: 'Researches deals',
    status: 'published',
    agent_type: 'classic',
    ownership: access === 'owner' ? 'user' : 'team',
    team_access: access === 'owner' ? null : access,
    access,
    allowed_actions: allowed,
  }) as Agent;

describe('AgentCard menu', () => {
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
    mocks.dispatch.mockClear();
    mocks.deleteAgent.mockReset();
  });

  const render = async (agent: Agent, section: string) => {
    await act(async () => {
      root.render(
        <MemoryRouter>
          <AgentCard agent={agent} agents={[agent]} section={section} />
        </MemoryRouter>,
      );
    });
  };

  const openMenu = async () => {
    const trigger = container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.card.actions"]',
    );
    if (!trigger) return [];
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
    return Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
  };

  const menuLabels = async () =>
    (await openMenu()).map((item) => item.textContent);

  it('gives the owner the full menu', async () => {
    await render(agentWith('owner', OWNER_ACTIONS), 'user');
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.logs',
      'agents.edit',
      'agents.exportAgent',
      'agents.shareWithTeam',
      'agents.card.pin',
      'agents.folders.moveToFolder',
      'agents.form.buttons.delete',
    ]);
  });

  it('gives an editor Logs, Edit, Export and Pin', async () => {
    await render(agentWith('editor', EDITOR_ACTIONS), 'team');
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.logs',
      'agents.edit',
      'agents.exportAgent',
      'agents.card.pin',
    ]);
  });

  it('brings Share and Delete back for an editor the owner allows', async () => {
    await render(
      agentWith('editor', [...EDITOR_ACTIONS, 'share', 'delete']),
      'team',
    );
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.logs',
      'agents.edit',
      'agents.exportAgent',
      'agents.shareWithTeam',
      'agents.card.pin',
      'agents.form.buttons.delete',
    ]);
  });

  it('gives a viewer Pin only', async () => {
    await render(agentWith('viewer', VIEWER_ACTIONS), 'team');
    expect(await menuLabels()).toEqual(['agents.card.pin']);
  });

  it('adds Logs for a viewer when the owner shares logs', async () => {
    await render(agentWith('viewer', [...VIEWER_ACTIONS, 'view_logs']), 'team');
    expect(await menuLabels()).toEqual([
      'agents.form.buttons.logs',
      'agents.card.pin',
    ]);
  });

  it('shows no menu to a viewer of a draft', async () => {
    await render(
      { ...agentWith('viewer', VIEWER_ACTIONS), status: 'draft' },
      'team',
    );
    expect(
      container.querySelector('button[aria-label="agents.card.actions"]'),
    ).toBeNull();
  });

  it('treats an own agent without access fields as the owner', async () => {
    const own = {
      ...agentWith('owner', []),
      access: undefined,
      allowed_actions: undefined,
    } as Agent;
    await render(own, 'user');
    expect(await menuLabels()).toHaveLength(7);
  });

  it('hides Logs on an own draft (no runs to show) but keeps the rest', async () => {
    await render(
      { ...agentWith('owner', OWNER_ACTIONS), status: 'draft' },
      'user',
    );
    const labels = await menuLabels();
    expect(labels).not.toContain('agents.form.buttons.logs');
    expect(labels).not.toContain('agents.card.pin');
    expect(labels).toContain('agents.edit');
  });

  it('gives Discovered cards Pin and Remove; the card itself opens the agent', async () => {
    await render(
      {
        ...agentWith('viewer', VIEWER_ACTIONS),
        shared_token: 'tok',
      },
      'shared',
    );
    expect(await menuLabels()).toEqual([
      'agents.card.pin',
      'agents.card.remove',
    ]);
  });

  it('opens the chat when a viewer clicks a published card', async () => {
    await render(agentWith('viewer', VIEWER_ACTIONS), 'team');
    await act(async () =>
      container.querySelector<HTMLElement>('[role="button"]')!.click(),
    );
    expect(mocks.dispatch).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'preference/setSelectedAgent' }),
    );
  });

  it('reports a refused delete in a toast', async () => {
    mocks.deleteAgent.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ message: 'Only the owner can delete' }),
    });
    await render(agentWith('owner', OWNER_ACTIONS), 'user');
    const items = await openMenu();
    await act(async () =>
      items
        .find((i) => i.textContent === 'agents.form.buttons.delete')!
        .click(),
    );
    await act(async () =>
      container.querySelector<HTMLElement>('[data-testid="confirm"]')!.click(),
    );
    expect(mocks.dispatch).toHaveBeenCalledWith({
      type: 'actionToast/showActionToast',
      payload: { variant: 'destructive', message: 'Only the owner can delete' },
    });
  });
});
