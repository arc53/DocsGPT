import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const mockState = { preference: { token: TOKEN } };
const mockDispatch = vi.fn((action: unknown) => action);

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(mockState),
  useDispatch: () => mockDispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      const params = Object.entries(opts)
        .filter(([k]) => k !== 'defaultValue' && k !== 'interpolation')
        .map(([k, v]) => `${k}=${v}`)
        .join(',');
      return params ? `${key}(${params})` : key;
    },
  }),
}));

const mockConfirm = { holdOpen: false };

// A light stand-in for the promise-aware confirm: title, description, body
// and submit; a rejected submit keeps it open with `error`.
vi.mock('../../modals/ConfirmationModal', async () => {
  const { useState } = await import('react');
  return {
    default: function MockConfirm(props: {
      modalState: string;
      setModalState: (s: string) => void;
      message: string;
      description?: string;
      submitLabel: string;
      error?: string | ((reason: unknown) => string);
      handleSubmit: () => unknown;
      handleCancel?: () => void;
      children?: React.ReactNode;
    }) {
      const [failed, setFailed] = useState<{ reason: unknown } | null>(null);
      if (props.modalState !== 'ACTIVE') return null;
      const submit = () => {
        const result = props.handleSubmit();
        if (result instanceof Promise) {
          result.then(
            // Held open, it shows what the real dialog shows while it closes.
            () => mockConfirm.holdOpen || props.setModalState('INACTIVE'),
            (reason: unknown) => setFailed({ reason }),
          );
        } else props.setModalState('INACTIVE');
      };
      return (
        <div role="dialog" data-testid="confirm">
          <h2>{props.message}</h2>
          {props.description && <p>{props.description}</p>}
          {props.children}
          {failed && (
            <p data-testid="confirm-error">
              {typeof props.error === 'function'
                ? props.error(failed.reason)
                : props.error}
            </p>
          )}
          <button
            type="button"
            onClick={() => {
              props.handleCancel?.();
              props.setModalState('INACTIVE');
            }}
          >
            cancel
          </button>
          <button type="button" onClick={submit}>
            {props.submitLabel}
          </button>
        </div>
      );
    },
  };
});

const listMembers = vi.fn();
const setMemberRole = vi.fn();
const removeMember = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    listMembers: (...a: unknown[]) => listMembers(...a),
    setMemberRole: (...a: unknown[]) => setMemberRole(...a),
    removeMember: (...a: unknown[]) => removeMember(...a),
  },
}));

import type { TeamMember } from '../../api/services/teamsService';
import type { Team } from '../teamsSlice';
import MembersTab from './MembersTab';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;

const TEAM: Team = {
  id: 't1',
  name: 'Operations',
  slug: 'operations',
  owner_id: 'lena',
};

const member = (
  user_id: string,
  team_role: 'owner' | 'admin' | 'editor' | 'viewer',
  pays_for?: TeamMember['pays_for'],
): TeamMember => ({
  user_id,
  email: `${user_id}@x.io`,
  role:
    team_role === 'owner' || team_role === 'admin'
      ? 'team_admin'
      : 'team_member',
  team_role,
  source: 'manual',
  pays_for,
});

describe('MembersTab: what a change pauses of what a member pays for', () => {
  let container: HTMLDivElement;
  let root: Root;

  const setMembers = (members: TeamMember[]) =>
    listMembers
      .mockReset()
      .mockResolvedValue({ members, total: members.length });

  beforeEach(() => {
    setMembers([
      member('lena', 'owner', { schedules: 0, outside_access: 0 }),
      member('dana', 'editor', { schedules: 2, outside_access: 0 }),
      member('jonas', 'admin', { schedules: 1, outside_access: 1 }),
      member('priya', 'viewer', { schedules: 0, outside_access: 0 }),
    ]);
    setMemberRole.mockReset().mockResolvedValue({ success: true });
    removeMember.mockReset().mockResolvedValue({ success: true });
    mockDispatch.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    mockConfirm.holdOpen = false;
    onOwnRoleChanged.mockClear();
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const onOwnRoleChanged = vi.fn();
  const render = async () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <MembersTab
            team={TEAM}
            role="admin"
            grants={[]}
            onOwnRoleChanged={onOwnRoleChanged}
          />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const rowOf = (email: string) =>
    Array.from(body().querySelectorAll<HTMLElement>('[data-slot="list-row"]'))
      .filter((row) => row.textContent?.includes(email))
      .at(0)!;

  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    );

  const confirm = () => body().querySelector('[data-testid="confirm"]');

  const openRemove = async (email: string) => {
    act(() =>
      rowOf(email)
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
  };

  const pickRole = async (email: string, role: string) => {
    const trigger =
      rowOf(email).querySelector<HTMLElement>('[role="combobox"]')!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    await flush();
    const option = Array.from(
      body().querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === `workspace.common.roles.${role}`)!;
    act(() => option.click());
    await flush();
  };

  it('says which schedules and outside access a removal pauses', async () => {
    await render();
    await openRemove('jonas@x.io');
    const text = confirm()!.textContent;
    expect(text).toContain(
      'payer.team.remove.schedules(count=1,name=jonas@x.io)',
    );
    expect(text).toContain(
      'payer.team.remove.schedulesDetail(name=jonas@x.io)',
    );
    expect(text).toContain('payer.team.remove.access(count=1)');
    expect(text).toContain('payer.team.remove.accessDetail(name=jonas@x.io)');
  });

  it('names only what the member pays for', async () => {
    await render();
    await openRemove('dana@x.io');
    const text = confirm()!.textContent;
    expect(text).toContain(
      'payer.team.remove.schedules(count=2,name=dana@x.io)',
    );
    expect(text).not.toContain('payer.team.remove.access');
  });

  it("says which of the team's connections a removal pauses", async () => {
    setMembers([
      member('lena', 'owner', { schedules: 0, outside_access: 0 }),
      member('ana', 'admin', {
        schedules: 0,
        outside_access: 0,
        connections: 2,
      }),
    ]);
    await render();
    await openRemove('ana@x.io');
    const text = confirm()!.textContent;
    expect(text).toContain(
      'payer.team.remove.connections(count=2,name=ana@x.io)',
    );
    expect(text).toContain(
      'payer.team.remove.connectionsDetail(name=ana@x.io)',
    );
  });

  it('asks first when a demotion below Admin pauses the connections', async () => {
    setMembers([
      member('lena', 'owner', { schedules: 0, outside_access: 0 }),
      member('ana', 'admin', {
        schedules: 0,
        outside_access: 0,
        connections: 1,
      }),
    ]);
    await render();
    await pickRole('ana@x.io', 'editor');
    expect(setMemberRole).not.toHaveBeenCalled();
    expect(confirm()!.textContent).toContain(
      'payer.team.remove.connections(count=1,name=ana@x.io)',
    );
  });

  it('counts no connections of someone already below Admin', async () => {
    // Their accounts paused when they lost Admin; leaving changes nothing.
    setMembers([
      member('lena', 'owner', { schedules: 0, outside_access: 0 }),
      member('ed', 'editor', {
        schedules: 0,
        outside_access: 0,
        connections: 1,
      }),
    ]);
    await render();
    await openRemove('ed@x.io');
    expect(confirm()!.textContent).not.toContain(
      'payer.team.remove.connections',
    );
    act(() => button('cancel', confirm()!)!.click());
    await flush();
    await pickRole('ed@x.io', 'viewer');
    expect(confirm()).toBeNull();
  });

  it("says the keys of the team's custom models a member added stay in use", async () => {
    setMembers([
      member('lena', 'owner', { schedules: 0, outside_access: 0 }),
      {
        ...member('ana', 'admin', { schedules: 1, outside_access: 0 }),
        custom_models: 2,
      },
      {
        ...member('ed', 'editor', { schedules: 0, outside_access: 0 }),
        custom_models: 0,
      },
    ]);
    await render();
    await openRemove('ana@x.io');
    expect(confirm()!.textContent).toContain(
      'payer.team.remove.customModels(count=2,name=ana@x.io)',
    );
    expect(confirm()!.textContent).toContain(
      'payer.team.remove.customModelsDetail',
    );
    act(() => button('cancel', confirm()!)!.click());
    await flush();
    await openRemove('ed@x.io');
    expect(confirm()!.textContent).not.toContain(
      'payer.team.remove.customModels',
    );
    act(() => button('cancel', confirm()!)!.click());
    await flush();
    // A demotion below Admin that asks anyway says it too.
    await pickRole('ana@x.io', 'viewer');
    expect(confirm()!.textContent).toContain(
      'payer.team.remove.customModels(count=2,name=ana@x.io)',
    );
  });

  it('adds no payer lines for a member who pays for nothing', async () => {
    await render();
    await openRemove('priya@x.io');
    expect(confirm()!.textContent).not.toContain('payer.team.remove');
  });

  it('adds no payer lines when the server sends no counts', async () => {
    setMembers([member('lena', 'owner'), member('dana', 'editor')]);
    await render();
    await openRemove('dana@x.io');
    expect(confirm()!.textContent).not.toContain('payer.team.remove');
  });

  it('asks first when a demotion pauses what the member pays for', async () => {
    await render();
    // Admin to Editor: outside access needs Admin, schedules don't.
    await pickRole('jonas@x.io', 'editor');
    expect(setMemberRole).not.toHaveBeenCalled();
    const text = confirm()!.textContent;
    expect(text).toContain('payer.team.demote.title(name=jonas@x.io');
    expect(text).toContain('payer.team.remove.access(count=1)');
    expect(text).not.toContain('payer.team.remove.schedules');
    act(() => button('payer.team.demote.submit', confirm()!)!.click());
    await flush();
    expect(setMemberRole).toHaveBeenCalledWith('t1', 'jonas', 'editor', TOKEN);
    expect(confirm()).toBeNull();
  });

  it('counts schedules too when the demotion goes to Viewer', async () => {
    await render();
    await pickRole('dana@x.io', 'viewer');
    const text = confirm()!.textContent;
    expect(text).toContain(
      'payer.team.remove.schedules(count=2,name=dana@x.io)',
    );
    act(() => button('cancel', confirm()!)!.click());
    await flush();
    expect(setMemberRole).not.toHaveBeenCalled();
  });

  it('changes the role at once when nothing would pause', async () => {
    await render();
    // Editor to Admin pauses nothing; Viewer to Editor neither.
    await pickRole('dana@x.io', 'admin');
    expect(confirm()).toBeNull();
    expect(setMemberRole).toHaveBeenCalledWith('t1', 'dana', 'admin', TOKEN);
    await pickRole('priya@x.io', 'editor');
    expect(confirm()).toBeNull();
    expect(setMemberRole).toHaveBeenCalledWith('t1', 'priya', 'editor', TOKEN);
  });

  it('keeps the demotion dialog worded while it closes', async () => {
    mockConfirm.holdOpen = true;
    await render();
    await pickRole('jonas@x.io', 'editor');
    act(() => button('payer.team.demote.submit', confirm()!)!.click());
    await flush();
    expect(setMemberRole).toHaveBeenCalled();
    expect(confirm()!.textContent).toContain(
      'payer.team.demote.title(name=jonas@x.io,role=workspace.common.roles.editor)',
    );
  });

  it('keeps the remove dialog worded while it closes', async () => {
    mockConfirm.holdOpen = true;
    await render();
    await openRemove('dana@x.io');
    act(() => button('settings.teams.remove', confirm()!)!.click());
    await flush();
    expect(removeMember).toHaveBeenCalled();
    expect(confirm()!.textContent).toContain(
      'settings.teams.removeMemberConfirmation(name=dana@x.io,team=Operations)',
    );
  });

  it('tells the page when you changed your own role', async () => {
    setMembers([
      member('lena', 'owner'),
      member('me', 'admin', { schedules: 0, outside_access: 0 }),
    ]);
    await render();
    await pickRole('me@x.io', 'editor');
    expect(setMemberRole).toHaveBeenCalledWith('t1', 'me', 'editor', TOKEN);
    expect(onOwnRoleChanged).toHaveBeenCalledTimes(1);
  });

  it("doesn't for someone else's role", async () => {
    await render();
    await pickRole('dana@x.io', 'admin');
    expect(onOwnRoleChanged).not.toHaveBeenCalled();
  });
});
