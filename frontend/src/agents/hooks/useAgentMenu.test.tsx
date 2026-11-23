import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

// The menu is a Radix dropdown; the tests only need its options.
vi.mock('@/components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: { label: string; onClick: () => void }[];
  }) => (
    <div data-testid="menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

// The Share dialog's props, from its last render.
const share = vi.hoisted(() => ({
  props: null as null | { onMoved?: () => void },
}));
vi.mock('../../teams/ShareToTeamModal', () => ({
  default: (props: { onMoved?: () => void }) => {
    share.props = props;
    return null;
  },
}));
vi.mock('../../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../../api/services/userService', () => ({ default: {} }));
vi.mock('../../workspace/move/useMoveToWorkspace', () => ({
  useMoveToWorkspace: () => ({ menuOption: () => null, dialog: null }),
}));

import { agentsListPath } from '../paths';
import type { Agent } from '../types';
import { useAgentMenu } from './useAgentMenu';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Harness({
  agent,
  onMovedToWorkspace,
}: {
  agent: Agent;
  onMovedToWorkspace?: () => void;
}) {
  const { menu, modals } = useAgentMenu({ agent, onMovedToWorkspace });
  return (
    <>
      {menu}
      {modals}
    </>
  );
}

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

const ownAgent = {
  id: 'a1',
  name: 'Deal Desk',
  status: 'published',
  access: 'owner',
  origin: 'own',
  workspace: { kind: 'personal', team_id: null },
  allowed_actions: ['use', 'pin', 'view', 'edit', 'share', 'delete'],
} as unknown as Agent;

describe('useAgentMenu Share', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    share.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (agent: Agent, onMovedToWorkspace?: () => void) =>
    act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/a1/edit']}>
          <Routes>
            <Route
              path="/agents/manage/a1/edit"
              element={
                <Harness
                  agent={agent}
                  onMovedToWorkspace={onMovedToWorkspace}
                />
              }
            />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>,
      );
    });

  const labels = () =>
    Array.from(container.querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );
  const openShare = () =>
    act(async () =>
      Array.from(container.querySelectorAll<HTMLButtonElement>('button'))
        .find((b) => b.textContent === 'agents.shareWithTeam')!
        .click(),
    );

  it("is offered on a team's agent to an Editor, to see who has access", async () => {
    await render({
      ...ownAgent,
      access: 'editor',
      origin: 'team',
      workspace: { kind: 'team', team_id: 't1' },
      allowed_actions: ['use', 'pin', 'view', 'edit'],
    } as unknown as Agent);
    expect(labels()).toContain('agents.shareWithTeam');
  });

  it("calls the page's reload when the dialog's offer moves the agent", async () => {
    const onMovedToWorkspace = vi.fn();
    await render(ownAgent, onMovedToWorkspace);
    await openShare();
    expect(share.props?.onMoved).toBeTypeOf('function');
    act(() => share.props!.onMoved!());
    expect(onMovedToWorkspace).toHaveBeenCalledTimes(1);
  });

  it('goes to the agent list after such a move by default', async () => {
    await render(ownAgent);
    await openShare();
    act(() => share.props!.onMoved!());
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      agentsListPath(),
    );
  });
});
