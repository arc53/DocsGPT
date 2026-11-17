import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const mockState = {
  preference: { token: TOKEN },
  workspace: {
    current: 'personal',
    workspaces: [{ id: 'personal', kind: 'personal', name: 'Personal' }],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};

// What a dispatched thunk's unwrap() does (setTeamOutsidePolicy here).
const mockUnwrap = vi.fn(() => Promise.resolve());
const mockDispatch = vi.fn((action: unknown) => {
  void action;
  return { unwrap: () => mockUnwrap() };
});

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

const getOutside = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    update: vi.fn(),
    listMembers: vi.fn(() => Promise.resolve({ members: [] })),
    transferOwner: vi.fn(),
    getOutside: (...a: unknown[]) => getOutside(...a),
  },
}));

const setTeamOutsidePolicy = vi.fn((arg: unknown) => ({
  type: 'teams/setOutsidePolicy',
  arg,
}));
vi.mock('../teamsSlice', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../teamsSlice')>()),
  setTeamOutsidePolicy: (arg: unknown) => setTeamOutsidePolicy(arg),
}));

vi.mock('../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks')>()),
  useDebouncedValue: <T,>(value: T) => value,
}));

import { TeamsApiError } from '../../api/services/teamsService';
import type { Team } from '../teamsSlice';
import SettingsTab from './SettingsTab';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

const body = () => document.body;

const team = (over: Partial<Team> = {}): Team => ({
  id: 't1',
  name: 'Operations',
  slug: 'operations',
  owner_id: 'lena',
  is_owner: false,
  outside_policy: 'admins',
  can_set_outside_policy: true,
  ...over,
});

const OUTSIDE = {
  outside_policy: 'admins',
  can_set_outside_policy: true,
  shares: [
    {
      id: 's1',
      resource_type: 'source',
      resource_id: 'src1',
      resource_name: 'Lane notes',
      team_id: 't2',
      name: 'Dev',
      shared_by: { user_id: 'me', label: 'me@x.io' },
      can_revoke: true,
      used_by_count: 2,
      paused_reason: null,
    },
    {
      id: 's2',
      resource_type: 'agent',
      resource_id: 'a1',
      resource_name: 'Carrier desk',
      team_id: 't2',
      name: 'Dev',
      shared_by: null,
      can_revoke: true,
      used_by_count: null,
      paused_reason: null,
    },
  ],
  published: [
    {
      agent_id: 'a5',
      name: 'Tender helper',
      outside_access: { api_key: true, public_link: false, webhook: false },
    },
  ],
};

describe('SettingsTab, who can take items outside', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getOutside.mockReset().mockResolvedValue(OUTSIDE);
    setTeamOutsidePolicy.mockClear();
    mockDispatch.mockClear();
    mockUnwrap.mockReset().mockImplementation(() => Promise.resolve());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (t: Team, role: 'owner' | 'admin' = 'admin') => {
    act(() => {
      root.render(
        <MemoryRouter>
          <SettingsTab team={t} role={role} />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const group = () =>
    body().querySelector<HTMLElement>(
      '[role="radiogroup"][aria-label="settings.teams.outside.label"]',
    );
  const radio = (policy: string) =>
    group()!.querySelector<HTMLButtonElement>(
      `[role="radio"][value="${policy}"]`,
    )!;
  const confirm = () =>
    body().querySelector<HTMLElement>('[data-testid="confirm"]');
  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    );

  it('shows the three choices, each described, with the current one picked', async () => {
    await render(team());
    expect(group()).not.toBeNull();
    const text = body().textContent ?? '';
    ['admins', 'editors', 'locked'].forEach((policy) => {
      expect(text).toContain(`settings.teams.outside.policy.${policy}`);
      expect(text).toContain(`settings.teams.outside.hint.${policy}`);
    });
    expect(radio('admins').getAttribute('aria-checked')).toBe('true');
    expect(radio('editors').disabled).toBe(false);
    expect(radio('locked').disabled).toBe(false);
  });

  it('leaves the section out when the server sends no policy', async () => {
    await render(team({ outside_policy: undefined }));
    expect(group()).toBeNull();
  });

  it('keeps an Admin of a locked team from picking, and says only the Owner unlocks', async () => {
    await render(
      team({ outside_policy: 'locked', can_set_outside_policy: false }),
    );
    ['admins', 'editors', 'locked'].forEach((policy) =>
      expect(radio(policy).disabled).toBe(true),
    );
    expect(body().textContent).toContain('settings.teams.outside.ownerOnly');
  });

  it('lets the Owner unlock, saying what comes back', async () => {
    await render(
      team({
        outside_policy: 'locked',
        can_set_outside_policy: true,
        is_owner: true,
      }),
      'owner',
    );
    expect(radio('admins').disabled).toBe(false);
    act(() => radio('admins').click());
    await flush();
    const dialog = confirm()!;
    expect(dialog.textContent).toContain(
      'settings.teams.outside.confirm.unlockTitle(team=Operations)',
    );
    expect(dialog.textContent).toContain(
      'settings.teams.outside.confirm.returns.shares(count=2,formatted=2)',
    );
    expect(dialog.textContent).toContain(
      'settings.teams.outside.confirm.returns.published(count=1,formatted=1)',
    );
    expect(dialog.textContent).toContain(
      'settings.teams.outside.confirm.returns.chatLinks',
    );
    act(() =>
      button('settings.teams.outside.confirm.submit.unlock', dialog)!.click(),
    );
    await flush();
    expect(setTeamOutsidePolicy).toHaveBeenCalledWith({
      teamId: 't1',
      policy: 'admins',
      token: TOKEN,
    });
    expect(confirm()).toBeNull();
  });

  it('asks before locking, listing what pauses, and that only the Owner unlocks', async () => {
    await render(team());
    act(() => radio('locked').click());
    await flush();
    // Nothing changes until the confirm.
    expect(setTeamOutsidePolicy).not.toHaveBeenCalled();
    const dialog = confirm()!;
    const text = dialog.textContent ?? '';
    expect(text).toContain(
      'settings.teams.outside.confirm.lockTitle(team=Operations)',
    );
    expect(text).toContain(
      'settings.teams.outside.confirm.pauses.shares(count=2,formatted=2)',
    );
    expect(text).toContain(
      'settings.teams.outside.confirm.pauses.published(count=1,formatted=1)',
    );
    expect(text).toContain('settings.teams.outside.confirm.pauses.chatLinks');
    expect(text).toContain('settings.teams.outside.confirm.ownerUnlocks');
    act(() =>
      button('settings.teams.outside.confirm.submit.lock', dialog)!.click(),
    );
    await flush();
    expect(setTeamOutsidePolicy).toHaveBeenCalledWith({
      teamId: 't1',
      policy: 'locked',
      token: TOKEN,
    });
  });

  it("doesn't tell the Owner that only the Owner unlocks", async () => {
    await render(team({ is_owner: true }), 'owner');
    act(() => radio('locked').click());
    await flush();
    expect(confirm()!.textContent).not.toContain(
      'settings.teams.outside.confirm.ownerUnlocks',
    );
  });

  it('says what changes when Editors are let in or out', async () => {
    await render(team());
    act(() => radio('editors').click());
    await flush();
    expect(confirm()!.textContent).toContain(
      'settings.teams.outside.confirm.toEditors',
    );
    act(() => button('cancel', confirm()!)?.click());
  });

  it('says what pauses for Editors when only Admins may again', async () => {
    await render(team({ outside_policy: 'editors' }));
    act(() => radio('admins').click());
    await flush();
    expect(confirm()!.textContent).toContain(
      'settings.teams.outside.confirm.toAdmins',
    );
  });

  it('shows a refusal inside the confirm, by its code', async () => {
    mockUnwrap.mockImplementation(() =>
      Promise.reject(
        new TeamsApiError(403, 'Only the owner', 'policy_owner_only'),
      ),
    );
    await render(team());
    act(() => radio('locked').click());
    await flush();
    act(() =>
      button('settings.teams.outside.confirm.submit.lock', confirm()!)!.click(),
    );
    await flush();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('settings.teams.errors.policyOwnerOnly');
  });

  it('still asks when what is outside could not be read, without counts', async () => {
    getOutside.mockRejectedValue(new Error('down'));
    await render(team());
    act(() => radio('locked').click());
    await flush();
    const text = confirm()!.textContent ?? '';
    expect(text).toContain('settings.teams.outside.confirm.pauses.sharesAny');
    expect(text).toContain(
      'settings.teams.outside.confirm.pauses.publishedAny',
    );
  });
});
