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
      children?: React.ReactNode;
    }) {
      const [failed, setFailed] = useState<{ reason: unknown } | null>(null);
      if (props.modalState !== 'ACTIVE') return null;
      const submit = () => {
        const result = props.handleSubmit();
        if (result instanceof Promise) {
          result.then(
            () => props.setModalState('INACTIVE'),
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
          <button type="button" onClick={submit}>
            {props.submitLabel}
          </button>
        </div>
      );
    },
  };
});

const listMembers = vi.fn();
const addMember = vi.fn();
const setMemberRole = vi.fn();
const removeMember = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    listMembers: (...a: unknown[]) => listMembers(...a),
    addMember: (...a: unknown[]) => addMember(...a),
    setMemberRole: (...a: unknown[]) => setMemberRole(...a),
    removeMember: (...a: unknown[]) => removeMember(...a),
  },
}));

import { TeamsApiError, type TeamGrant } from '../../api/services/teamsService';
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

const MEMBERS = [
  {
    user_id: 'lena',
    email: 'lena@x.io',
    role: 'team_admin',
    team_role: 'owner',
    source: 'manual',
  },
  {
    user_id: 'dana',
    email: 'dana@x.io',
    role: 'team_member',
    team_role: 'editor',
    source: 'manual',
  },
  {
    user_id: 'me',
    email: 'me@x.io',
    role: 'team_admin',
    team_role: 'admin',
    source: 'manual',
  },
];

const grant = (over: Partial<TeamGrant> = {}): TeamGrant => ({
  resource_type: 'agent',
  resource_id: 'a1',
  access_level: 'viewer',
  target_user_id: null,
  resource_name: 'Lane pricing assistant',
  owner_id: 'dana',
  owner_label: 'dana@x.io',
  ...over,
});

const refusal = (status: number, code: string) =>
  Object.assign(new TeamsApiError(status, 'server words'), { code });

describe('MembersTab', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listMembers
      .mockReset()
      .mockResolvedValue({ members: MEMBERS, total: MEMBERS.length });
    addMember.mockReset().mockResolvedValue({ success: true });
    setMemberRole.mockReset().mockResolvedValue({ success: true });
    removeMember.mockReset().mockResolvedValue({ success: true });
    mockDispatch.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    role: 'owner' | 'admin' | 'editor' | 'viewer' = 'admin',
    grants: TeamGrant[] = [],
  ) => {
    act(() => {
      root.render(
        <MemoryRouter>
          <MembersTab team={TEAM} role={role} grants={grants} />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const rowOf = (email: string) =>
    Array.from(body().querySelectorAll<HTMLElement>('[data-slot="list-row"]'))
      .filter((row) => row.textContent?.includes(email))
      .at(0)!;

  const toasts = () =>
    mockDispatch.mock.calls
      .map(([action]) => action as { payload?: { message?: string } })
      .filter((a) => a?.payload?.message)
      .map((a) => a.payload!.message);

  const typeInto = (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    act(() => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const openSelect = async (trigger: HTMLElement) => {
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
  };

  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    )!;

  it('shows each member in the four roles, the owner without a select', async () => {
    await render();
    const owner = rowOf('lena@x.io');
    expect(owner.querySelector('[role="combobox"]')).toBeNull();
    expect(owner.textContent).toContain('workspace.common.roles.owner');
    expect(
      owner.querySelector('button[aria-label="settings.teams.remove"]'),
    ).toBeNull();
    const dana = rowOf('dana@x.io');
    const select = dana.querySelector<HTMLElement>('[role="combobox"]')!;
    expect(select.textContent).toContain('workspace.common.roles.editor');
    expect(
      rowOf('me@x.io').querySelector('[role="combobox"]')?.textContent,
    ).toContain('workspace.common.roles.admin');
  });

  it('offers Viewer, Editor and Admin, never Owner', async () => {
    await render();
    const trigger =
      rowOf('dana@x.io').querySelector<HTMLElement>('[role="combobox"]')!;
    await openSelect(trigger);
    const options = Array.from(body().querySelectorAll('[role="option"]')).map(
      (o) => o.textContent,
    );
    expect(options).toEqual([
      'workspace.common.roles.viewer',
      'workspace.common.roles.editor',
      'workspace.common.roles.admin',
    ]);
  });

  it('adds a member as a Viewer unless another role is picked', async () => {
    await render();
    act(() => button('settings.teams.addMember').click());
    await flush();
    const modal = body().querySelector('[data-slot="modal-content"]')!;
    expect(modal.textContent).toContain('settings.teams.roleHints.viewer');
    typeInto(
      modal.querySelector<HTMLInputElement>('input[type="email"]')!,
      'new@x.io',
    );
    act(() => button('settings.teams.add', modal).click());
    await flush();
    expect(addMember).toHaveBeenCalledWith(
      't1',
      { email: 'new@x.io', role: 'viewer' },
      TOKEN,
    );
  });

  it('says a last-admin refusal in its own words', async () => {
    setMemberRole.mockRejectedValue(refusal(409, 'last_admin'));
    await render();
    // Pick Viewer for yourself (the last admin).
    const trigger =
      rowOf('me@x.io').querySelector<HTMLElement>('[role="combobox"]')!;
    await openSelect(trigger);
    const viewer = Array.from(
      body().querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === 'workspace.common.roles.viewer')!;
    act(() => viewer.click());
    await flush();
    expect(setMemberRole).toHaveBeenCalledWith('t1', 'me', 'viewer', TOKEN);
    expect(toasts()).toContain('settings.teams.errors.lastAdmin');
    expect(toasts()).not.toContain('server words');
  });

  it('says an owner refusal on remove in its own words, in the dialog', async () => {
    removeMember.mockRejectedValue(refusal(403, 'owner_protected'));
    await render();
    act(() =>
      rowOf('dana@x.io')
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    act(() => button('settings.teams.remove', confirm).click());
    await flush();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.errors.ownerProtected');
  });

  it('lists what a member shares with the team in the remove dialog', async () => {
    await render('admin', [
      grant(),
      grant({
        resource_type: 'source',
        resource_id: 's1',
        resource_name: 'Lane pricing notes',
      }),
      // A per-person grant of the same item counts once.
      grant({ target_user_id: 'me', access_level: 'editor' }),
      // Someone else's item isn't Dana's to take away.
      grant({
        resource_id: 'a2',
        resource_name: 'Escalation reply',
        owner_id: 'tomas',
      }),
    ]);
    act(() =>
      rowOf('dana@x.io')
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    expect(confirm.textContent).toContain(
      'settings.teams.removeMember.teamItemsStay(name=dana@x.io,team=Operations)',
    );
    expect(confirm.textContent).toContain(
      'settings.teams.removeMember.personalItems(count=2,name=dana@x.io,team=Operations)',
    );
    expect(confirm.textContent).toContain('Lane pricing assistant');
    expect(confirm.textContent).toContain('Lane pricing notes');
    expect(confirm.textContent).not.toContain('Escalation reply');
    // They pause while Dana is out and come back if she's added again.
    expect(confirm.textContent).toContain(
      'settings.teams.removeMember.personalItemsPaused(name=dana@x.io,team=Operations)',
    );
    expect(confirm.textContent).not.toContain(
      'settings.teams.removeMember.personalItemsHint',
    );
  });

  it('leaves the personal items line out when the member shares nothing', async () => {
    await render('admin', [grant({ owner_id: 'tomas' })]);
    act(() =>
      rowOf('dana@x.io')
        .querySelector<HTMLButtonElement>(
          'button[aria-label="settings.teams.remove"]',
        )!
        .click(),
    );
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    expect(confirm.textContent).toContain(
      'settings.teams.removeMember.teamItemsStay',
    );
    expect(confirm.textContent).not.toContain(
      'settings.teams.removeMember.personalItems',
    );
  });

  it('gives an Editor or a Viewer no member controls', async () => {
    for (const role of ['editor', 'viewer'] as const) {
      await render(role);
      expect(body().querySelectorAll('[role="combobox"]')).toHaveLength(0);
      expect(
        body().querySelectorAll('button[aria-label="settings.teams.remove"]'),
      ).toHaveLength(0);
      expect(button('settings.teams.addMember')).toBeUndefined();
      // Roles still read as words.
      expect(rowOf('dana@x.io').textContent).toContain(
        'workspace.common.roles.editor',
      );
    }
  });
});
