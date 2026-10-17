import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';

type MockTeam = { id: string; name: string; member_role: string };

const mockState: {
  preference: { token: string };
  teams: { teams: MockTeam[]; currentTeamId: string | null };
} = {
  preference: { token: 'tok' },
  teams: { teams: [], currentTeamId: null },
};

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => () => undefined,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));

vi.mock('../hooks', () => ({ useDarkTheme: () => [false] }));

// Render the menu inline so items are clickable without Radix pointer events.
vi.mock('../components/ui/dropdown-menu', () => {
  const Pass = ({ children }: { children?: ReactNode }) => <>{children}</>;
  return {
    DropdownMenu: Pass,
    DropdownMenuTrigger: Pass,
    DropdownMenuContent: Pass,
    DropdownMenuLabel: Pass,
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

const TEAMS: MockTeam[] = [
  { id: 't1', name: 'Customer Support', member_role: 'team_admin' },
  { id: 't2', name: 'People Ops', member_role: 'team_member' },
];

let container: HTMLDivElement;
let root: Root;

const render = () => {
  act(() => {
    root.render(<TeamSwitcher />);
  });
};

const menuItems = () =>
  Array.from(container.querySelectorAll('[data-menu-item]')).map(
    (el) => el.textContent,
  );

const clickItem = (label: string) => {
  const item = Array.from(container.querySelectorAll('[data-menu-item]')).find(
    (el) => el.textContent === label,
  ) as HTMLButtonElement;
  act(() => item.click());
};

beforeEach(() => {
  navigate.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('TeamSwitcher footer action', () => {
  it('offers Create team when the user has no teams', () => {
    mockState.teams = { teams: [], currentTeamId: null };
    render();

    expect(menuItems()).toEqual(['teams.switcher.createTeam']);
    clickItem('teams.switcher.createTeam');
    expect(navigate).toHaveBeenCalledWith('/teams', {
      state: { create: true },
    });
  });

  it('offers Manage teams from the personal account once a team exists', () => {
    mockState.teams = { teams: TEAMS, currentTeamId: null };
    render();

    expect(menuItems()).toEqual([
      'Customer Support',
      'People Ops',
      'teams.switcher.manageTeams',
    ]);
    clickItem('teams.switcher.manageTeams');
    expect(navigate).toHaveBeenCalledWith('/teams');
  });

  it('shows one Manage teams entry inside a team, not a per-team one', () => {
    mockState.teams = { teams: TEAMS, currentTeamId: 't1' };
    render();

    expect(menuItems()).toEqual([
      'teams.switcher.personal',
      'People Ops',
      'teams.switcher.manageTeams',
    ]);
  });
});
