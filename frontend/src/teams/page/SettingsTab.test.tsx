import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

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

// What a dispatched thunk's unwrap() does (deleteTeam here).
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
      submitLabel: string;
      error?: string | ((reason: unknown) => string);
      handleSubmit: () => unknown;
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

const update = vi.fn();
const listMembers = vi.fn();
const transferOwner = vi.fn();
vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    update: (...a: unknown[]) => update(...a),
    listMembers: (...a: unknown[]) => listMembers(...a),
    transferOwner: (...a: unknown[]) => transferOwner(...a),
  },
}));

// Searches answer at once here.
vi.mock('../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks')>()),
  useDebouncedValue: <T,>(value: T) => value,
}));

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

const TEAM: Team = {
  id: 't1',
  name: 'Operations',
  slug: 'operations',
  owner_id: 'me',
  is_owner: true,
  description: 'Freight desk',
};

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

describe('SettingsTab', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    update.mockReset().mockResolvedValue({ success: true });
    transferOwner.mockReset().mockResolvedValue({ success: true });
    listMembers.mockReset().mockResolvedValue({
      members: [
        {
          user_id: 'me',
          email: 'me@x.io',
          role: 'team_admin',
          team_role: 'owner',
        },
        {
          user_id: 'dana',
          email: 'dana@x.io',
          role: 'team_member',
          team_role: 'editor',
        },
      ],
      total: 2,
    });
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

  const render = async (
    team: Team = TEAM,
    role: 'owner' | 'admin' = 'owner',
  ) => {
    act(() => {
      root.render(
        <MemoryRouter initialEntries={['/teams/t1/settings']}>
          <SettingsTab team={team} role={role} />
          <Where />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const button = (label: string, scope: ParentNode = body()) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    );

  const actions = () =>
    mockDispatch.mock.calls.map(([action]) => action as { type?: string });

  const deleteAndConfirm = async () => {
    act(() => button('settings.teams.deleteTeam')!.click());
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    act(() => button('settings.teams.delete', confirm)!.click());
    await flush();
  };

  it("names what the team still owns when it can't be deleted, and opens it", async () => {
    mockUnwrap.mockImplementation(() =>
      Promise.reject({
        name: 'TeamsApiError',
        message: 'Move or delete the team items first',
        code: 'team_not_empty',
        counts: { agent: 3, source: 2, folder: 1, schedules: 4 },
      }),
    );
    await render();
    await deleteAndConfirm();
    // The confirm closes; the page says why, with the counts.
    expect(body().querySelector('[data-testid="confirm"]')).toBeNull();
    const alert = body().querySelector('[data-slot="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.teams.notEmpty.title(name=Operations)',
    );
    expect(alert.textContent).toContain(
      'settings.teams.notEmpty.counts.agent(count=3)',
    );
    expect(alert.textContent).toContain(
      'settings.teams.notEmpty.counts.source(count=2)',
    );
    expect(alert.textContent).toContain(
      'settings.teams.notEmpty.counts.folder(count=1)',
    );
    expect(alert.textContent).toContain(
      'settings.teams.notEmpty.counts.other(count=4)',
    );
    const open = button(
      'settings.teams.notEmpty.open(name=Operations)',
      alert,
    )!;
    act(() => open.click());
    await flush();
    expect(actions()).toContainEqual(
      expect.objectContaining({
        type: 'workspace/switched',
        payload: { id: 't1', reason: 'user' },
      }),
    );
    expect(body().querySelector('[data-testid="where"]')?.textContent).toBe(
      '/agents/manage',
    );
  });

  it('keeps any other refusal in the dialog', async () => {
    mockUnwrap.mockImplementation(() =>
      Promise.reject({ name: 'TeamsApiError', message: 'Only the owner' }),
    );
    await render();
    await deleteAndConfirm();
    expect(
      body().querySelector('[data-testid="confirm-error"]')?.textContent,
    ).toBe('Only the owner');
  });

  it('goes back to the teams list once the team is deleted', async () => {
    await render();
    await deleteAndConfirm();
    expect(body().querySelector('[data-testid="where"]')?.textContent).toBe(
      '/teams',
    );
  });

  it('saves the name and description', async () => {
    await render();
    const name = body().querySelector<HTMLInputElement>(
      'input[name="team-name"]',
    )!;
    expect(name.value).toBe('Operations');
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    act(() => {
      setter.call(name, 'Ops desk');
      name.dispatchEvent(new Event('input', { bubbles: true }));
    });
    act(() => button('settings.teams.save')!.click());
    await flush();
    expect(update).toHaveBeenCalledWith(
      't1',
      { name: 'Ops desk', description: 'Freight desk' },
      TOKEN,
    );
  });

  const openPicker = async () => {
    const trigger = body().querySelector<HTMLElement>(
      '[role="combobox"][aria-label="settings.teams.transfer.memberLabel"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
      trigger.click();
    });
    await flush();
  };
  const pickerOptions = () =>
    Array.from(body().querySelectorAll<HTMLElement>('[role="option"]'));

  it('lets the owner hand the team to another member', async () => {
    await render();
    await openPicker();
    const options = pickerOptions();
    // Not yourself.
    expect(options.map((o) => o.textContent)).toEqual(['dana@x.io']);
    await act(async () => options[0].click());
    act(() => button('settings.teams.transfer.action')!.click());
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    expect(confirm.textContent).toContain(
      'settings.teams.transfer.confirm(name=dana@x.io,team=Operations)',
    );
    act(() => button('settings.teams.transfer.submit', confirm)!.click());
    await flush();
    expect(transferOwner).toHaveBeenCalledWith('t1', 'dana', TOKEN);
  });

  // A team can be larger than one page of members: the server searches.
  it('finds any member by name, past the first page', async () => {
    listMembers.mockImplementation(
      (_id: string, _token: string, opts?: { q?: string }) =>
        Promise.resolve(
          opts?.q === 'zed'
            ? {
                members: [
                  {
                    user_id: 'zed',
                    email: 'zed@x.io',
                    role: 'team_member',
                    team_role: 'viewer',
                  },
                ],
                total: 1,
              }
            : {
                members: [
                  {
                    user_id: 'dana',
                    email: 'dana@x.io',
                    role: 'team_member',
                    team_role: 'editor',
                  },
                ],
                total: 240,
              },
        ),
    );
    await render();
    await openPicker();
    const input = body().querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, 'zed');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await flush();
    expect(listMembers).toHaveBeenCalledWith(
      't1',
      TOKEN,
      expect.objectContaining({ q: 'zed' }),
    );
    const options = pickerOptions();
    expect(options.map((o) => o.textContent)).toEqual(['zed@x.io']);
    await act(async () => options[0].click());
    act(() => button('settings.teams.transfer.action')!.click());
    await flush();
    const confirm = body().querySelector('[data-testid="confirm"]')!;
    act(() => button('settings.teams.transfer.submit', confirm)!.click());
    await flush();
    expect(transferOwner).toHaveBeenCalledWith('t1', 'zed', TOKEN);
  });

  it('gives an Admin who is not the owner no transfer or delete', async () => {
    await render({ ...TEAM, is_owner: false, owner_id: 'lena' }, 'admin');
    expect(button('settings.teams.save')).toBeDefined();
    expect(button('settings.teams.deleteTeam')).toBeUndefined();
    expect(button('settings.teams.transfer.action')).toBeUndefined();
    expect(listMembers).not.toHaveBeenCalled();
  });
});
