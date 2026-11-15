import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';

type MockRow = {
  id: string;
  kind: 'personal' | 'team';
  name: string;
  role?: string;
  member_count?: number;
};

const PERSONAL: MockRow = {
  id: 'personal',
  kind: 'personal',
  name: 'Personal',
};
const OPS: MockRow = {
  id: 't1',
  kind: 'team',
  name: 'Operations',
  role: 'admin',
  member_count: 12,
};
const SALES: MockRow = {
  id: 't2',
  kind: 'team',
  name: 'Sales',
  role: 'viewer',
  member_count: 8,
};

const initialState = {
  preference: { token: 'tok' },
  workspace: {
    current: 'personal',
    workspaces: [PERSONAL] as MockRow[],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};
const mock = { state: initialState };

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mock.state),
  useDispatch: () => dispatch,
}));

// Keys with their options, so a row's words and numbers can be checked.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts
        ? `${key}(${Object.entries(opts)
            .filter(([k]) => k !== 'interpolation')
            .map(([k, v]) => `${k}=${String(v)}`)
            .join(',')})`
        : key,
  }),
}));

const navigate = vi.fn();
const location = { pathname: '/agents/manage', search: '' };
vi.mock('react-router-dom', () => ({
  useNavigate: () => navigate,
  useLocation: () => location,
}));

vi.mock('../hooks', () => ({ useDarkTheme: () => [false] }));

// Render the menu inline so items are clickable without Radix pointer events.
vi.mock('../components/ui/dropdown-menu', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>;
  return {
    DropdownMenu: Pass,
    DropdownMenuTrigger: Pass,
    DropdownMenuContent: Pass,
    DropdownMenuLabel: ({ children }: { children?: ReactNode }) => (
      <div data-menu-label>{children}</div>
    ),
    DropdownMenuSeparator: () => null,
    DropdownMenuItem: ({
      children,
      onSelect,
    }: {
      children?: ReactNode;
      onSelect?: () => void;
    }) => (
      <button type="button" data-menu-item onClick={onSelect}>
        {children}
      </button>
    ),
  };
});

import TeamSwitcher from './TeamSwitcher';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let root: Root;

const setWorkspaces = (current: string, rows: MockRow[]) => {
  mock.state = {
    ...mock.state,
    workspace: { ...mock.state.workspace, current, workspaces: rows },
  };
};

const render = (collapsed = false) => {
  act(() => {
    root.render(<TeamSwitcher collapsed={collapsed} />);
  });
};

const items = () =>
  Array.from(container.querySelectorAll<HTMLButtonElement>('[data-menu-item]'));

const item = (text: string) =>
  items().find((el) => el.textContent?.includes(text))!;

beforeEach(() => {
  navigate.mockReset();
  dispatch.mockReset();
  location.pathname = '/agents/manage';
  location.search = '';
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('TeamSwitcher rows', () => {
  it('offers Personal and Create team when the user has no teams', () => {
    setWorkspaces('personal', [PERSONAL]);
    render();
    expect(items().map((el) => el.textContent)).toEqual([
      'workspace.switcher.personalworkspace.switcher.onlyYou',
      'teams.switcher.createTeam',
    ]);
    act(() => item('teams.switcher.createTeam').click());
    expect(navigate).toHaveBeenCalledWith('/teams', {
      state: { create: true },
    });
  });

  it('says who is in each team and the role there', () => {
    setWorkspaces('personal', [PERSONAL, OPS, SALES]);
    render();
    const texts = items().map((el) => el.textContent);
    expect(texts).toEqual([
      'workspace.switcher.personalworkspace.switcher.onlyYou',
      // Each team row leads with the team's initial.
      'OOperationsworkspace.switcher.teamMeta(count=12,role=workspace.common.roles.admin)',
      'SSalesworkspace.switcher.teamMeta(count=8,role=workspace.common.roles.viewer)',
      'teams.switcher.manageTeams',
    ]);
    expect(container.textContent).toContain('workspace.switcher.teams');
    act(() => item('teams.switcher.manageTeams').click());
    expect(navigate).toHaveBeenCalledWith('/teams');
  });

  it('marks the current workspace with a check', () => {
    setWorkspaces('t1', [PERSONAL, OPS, SALES]);
    render();
    const checked = items().filter((el) => el.querySelector('.lucide-check'));
    expect(checked.map((el) => el.textContent)).toEqual([
      'OOperationsworkspace.switcher.teamMeta(count=12,role=workspace.common.roles.admin)',
    ]);
  });
});

describe('TeamSwitcher header', () => {
  it('reads Personal · Only you in Personal', () => {
    setWorkspaces('personal', [PERSONAL, OPS]);
    render();
    const trigger = container.querySelector(
      'button[aria-label="teams.switcher.ariaLabel"]',
    )!;
    expect(trigger.textContent).toContain('workspace.switcher.personal');
    expect(trigger.textContent).toContain('workspace.switcher.onlyYou');
  });

  it('reads the team, Team and the role inside a team', () => {
    setWorkspaces('t1', [PERSONAL, OPS]);
    render();
    const trigger = container.querySelector(
      'button[aria-label="teams.switcher.ariaLabel"]',
    )!;
    expect(trigger.textContent).toContain('Operations');
    expect(trigger.textContent).toContain(
      'workspace.switcher.teamRole(role=workspace.common.roles.admin)',
    );
  });

  it('shows only the initial when collapsed inside a team', () => {
    setWorkspaces('t1', [PERSONAL, OPS]);
    render(true);
    const trigger = container.querySelector(
      'button[aria-label="teams.switcher.ariaLabel"]',
    )!;
    expect(trigger.textContent).toBe('O');
  });
});

describe('TeamSwitcher switching', () => {
  it('switches to a team the user picks', () => {
    setWorkspaces('personal', [PERSONAL, OPS, SALES]);
    render();
    act(() => item('Sales').click());
    expect(dispatch).toHaveBeenCalledWith({
      type: 'workspace/switched',
      payload: { id: 't2', reason: 'user' },
    });
  });

  it('switches back to Personal', () => {
    setWorkspaces('t1', [PERSONAL, OPS]);
    render();
    act(() => item('workspace.switcher.personal').click());
    expect(dispatch).toHaveBeenCalledWith({
      type: 'workspace/switched',
      payload: { id: 'personal', reason: 'user' },
    });
  });

  it('does nothing for the workspace already open', () => {
    setWorkspaces('t1', [PERSONAL, OPS]);
    render();
    act(() => item('Operations').click());
    expect(dispatch).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("leaves an item's page for its list", () => {
    location.pathname = '/agents/manage/edit/a1';
    setWorkspaces('personal', [PERSONAL, OPS]);
    render();
    act(() => item('Operations').click());
    expect(navigate).toHaveBeenCalledWith('/agents/manage', { replace: true });
  });

  it('stays on a list page', () => {
    location.pathname = '/settings/tools';
    setWorkspaces('personal', [PERSONAL, OPS]);
    render();
    act(() => item('Operations').click());
    expect(navigate).not.toHaveBeenCalled();
    expect(dispatch).toHaveBeenCalled();
  });
});
