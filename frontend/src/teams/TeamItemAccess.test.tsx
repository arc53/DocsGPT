import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

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
  }),
}));

// Take over needs the session and the toast; tested in the .payer file.
vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({ preference: { token: null } }),
}));

import TeamItemAccess, { type TeamItemShares } from './TeamItemAccess';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const info = (over: Partial<TeamItemShares> = {}): TeamItemShares => ({
  shares: [],
  workspace: { kind: 'team', team_id: 't1', name: 'Operations' },
  members_count: 12,
  access: 'admin',
  team_role: 'admin',
  origin: 'team',
  outside_access: {
    api_key: true,
    public_link: false,
    webhook: true,
    paid_by: { user_id: 'u2', label: 'dana@meridian.example' },
  },
  ...over,
});

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

const render = (
  props: Partial<React.ComponentProps<typeof TeamItemAccess>> = {},
) => {
  act(() => {
    root.render(
      <MemoryRouter>
        <TeamItemAccess
          resourceType="agent"
          info={info()}
          currentUserId="u1"
          {...props}
        />
      </MemoryRouter>,
    );
  });
  return container.textContent ?? '';
};

describe('TeamItemAccess', () => {
  it('shows the team as one row and no list of people', () => {
    const page = render();
    expect(page).toContain('workspace.share.everyoneInTeam(team=Operations)');
    expect(page).toContain('workspace.share.members(count=12');
    expect(page).not.toContain('settings.teams.share.peopleWithAccess');
    expect(container.querySelector('[role="combobox"]')).toBeNull();
  });

  it("names the caller's role in the team", () => {
    const page = render({ info: info({ team_role: 'editor' }) });
    expect(page).toContain('workspace.share.yourRole(role=');
    expect(page).toContain('workspace.common.roles.editor');
    expect(page).toContain('workspace.share.fromTeam');
  });

  it('lists outside access with who pays for it', () => {
    const page = render();
    expect(page).toContain('workspace.share.outside');
    expect(page).toContain('workspace.share.publicLink');
    expect(page).toContain('workspace.share.off');
    expect(page).toContain(
      'workspace.share.onPaidBy(name=dana@meridian.example)',
    );
    expect(page).toContain('workspace.share.adminsOnly');
  });

  it('says "you" when the caller pays', () => {
    const page = render({
      info: info({
        outside_access: {
          api_key: true,
          public_link: false,
          webhook: false,
          paid_by: { user_id: 'u1', label: 'lena@meridian.example' },
        },
      }),
    });
    expect(page).toContain(
      'workspace.share.onPaidBy(name=workspace.share.payerYou)',
    );
  });

  it('has no outside section for an item other than an agent', () => {
    const page = render({
      resourceType: 'source',
      info: info({ outside_access: undefined }),
    });
    expect(page).not.toContain('workspace.share.outside');
  });

  it('offers Manage members to an Admin only', () => {
    render();
    const manage = () =>
      Array.from(container.querySelectorAll('a')).find((a) =>
        a.textContent?.includes('workspace.share.manageMembers'),
      );
    expect(manage()?.getAttribute('href')).toBe('/teams/t1');
    render({ info: info({ team_role: 'editor' }) });
    expect(manage()).toBeUndefined();
    render({ info: info({ team_role: 'owner' }) });
    expect(manage()).toBeTruthy();
  });
});
