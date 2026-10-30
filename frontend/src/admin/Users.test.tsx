import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const mockDispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'tok',
  useDispatch: () => mockDispatch,
}));

// Render each row's ⋯ menu inline so tests can click its options.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: Array<{ label: string; onClick: () => void }>;
  }) => (
    <div data-testid="user-menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

// The confirm's props; the test calls its handleSubmit directly.
const confirmProps: { current: Record<string, unknown> | null } = {
  current: null,
};
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: Record<string, unknown>) => {
    confirmProps.current = props;
    return null;
  },
}));
vi.mock('./UserUsageModal', () => ({ default: () => null }));
vi.mock('./UserQuotaModal', () => ({ default: () => null }));

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: async () => body });

const getUsers = vi.fn();
const getAdmins = vi.fn();
const getUser = vi.fn();
const grantAdmin = vi.fn();
const revokeAdmin = vi.fn();
const setUserActive = vi.fn();
const revokeSessions = vi.fn();
vi.mock('../api/services/adminService', () => ({
  default: {
    getUsers: (...a: unknown[]) => getUsers(...a),
    getAdmins: (...a: unknown[]) => getAdmins(...a),
    getUser: (...a: unknown[]) => getUser(...a),
    grantAdmin: (...a: unknown[]) => grantAdmin(...a),
    revokeAdmin: (...a: unknown[]) => revokeAdmin(...a),
    setUserActive: (...a: unknown[]) => setUserActive(...a),
    revokeSessions: (...a: unknown[]) => revokeSessions(...a),
  },
}));

import Users from './Users';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flush = async () => {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
};

describe('admin Users actions', () => {
  let container: HTMLDivElement;
  let root: Root;

  const render = async (
    user: Record<string, unknown> = {},
    admins: string[] = [],
  ) => {
    getUsers.mockImplementation(() =>
      respond({
        success: true,
        total: 1,
        users: [{ user_id: 'priya', active: true, ...user }],
      }),
    );
    getAdmins.mockImplementation(() =>
      respond({
        success: true,
        admins: admins.map((user_id) => ({ user_id })),
      }),
    );
    await act(async () => root.render(<Users />));
    await flush();
  };

  beforeEach(() => {
    mockDispatch.mockReset();
    confirmProps.current = null;
    [
      getUsers,
      getAdmins,
      getUser,
      grantAdmin,
      revokeAdmin,
      setUserActive,
      revokeSessions,
    ].forEach((m) => m.mockReset());
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const clickOption = async (label: string) => {
    const option = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-testid="user-menu"] button',
      ),
    ).find((b) => b.textContent === label)!;
    await act(async () => option.click());
    await flush();
  };

  const toasts = () =>
    mockDispatch.mock.calls.map(
      ([action]) => (action as { payload: Record<string, unknown> }).payload,
    );

  const submitConfirm = async () => {
    const run = confirmProps.current!.handleSubmit as () => Promise<unknown>;
    let result!: Promise<unknown>;
    await act(async () => {
      result = run();
      await result.catch(() => undefined);
    });
    await flush();
    return result;
  };

  it('a row shows the email over the full user id', async () => {
    await render({ email: 'priya@example.com' });
    const cell = container.querySelector('tbody td')!;
    expect(cell.textContent).toContain('priya@example.com');
    expect(cell.textContent).toContain('priya');
  });

  it('a row without an email shows the user id alone', async () => {
    await render({ email: null });
    expect(container.querySelector('tbody td')!.textContent).toBe('priya');
  });

  it('the detail dialog shows the email and the user id', async () => {
    await render({ email: 'priya@example.com' });
    getUser.mockImplementation(() =>
      respond({
        success: true,
        user: { user_id: 'priya', email: 'priya@example.com', active: true },
        roles: ['user'],
        counts: {},
        recent_events: [],
      }),
    );
    await clickOption('View details');
    expect(getUser).toHaveBeenCalledWith('priya', 'tok');
    const dialog = document.body.querySelector('[role="dialog"]')!;
    const items = Array.from(dialog.querySelectorAll('dt')).map((dt) => [
      dt.textContent,
      dt.nextElementSibling?.textContent,
    ]);
    expect(items).toContainEqual(['Email', 'priya@example.com']);
    expect(items).toContainEqual(['User ID', 'priya']);
  });

  it('the detail dialog says when no email is on file', async () => {
    await render();
    getUser.mockImplementation(() =>
      respond({
        success: true,
        user: { user_id: 'priya', email: null, active: true },
        roles: ['user'],
        counts: {},
        recent_events: [],
      }),
    );
    await clickOption('View details');
    const dialog = document.body.querySelector('[role="dialog"]')!;
    const items = Array.from(dialog.querySelectorAll('dt')).map((dt) => [
      dt.textContent,
      dt.nextElementSibling?.textContent,
    ]);
    expect(items).toContainEqual(['Email', 'Not on file']);
    expect(items).toContainEqual(['User ID', 'priya']);
  });

  it('a confirm names the user by email and id (emails are not unique)', async () => {
    await render({ email: 'priya@example.com' });
    await clickOption('Deactivate');
    expect(confirmProps.current?.message).toBe(
      'Deactivate "priya@example.com (priya)"?',
    );
  });

  it('a confirm names a user without an email by id alone', async () => {
    await render({}, ['priya']);
    await clickOption('Revoke admin');
    expect(confirmProps.current?.message).toBe('Revoke admin from "priya"?');
  });

  it('Make admin shows no success toast and reloads the list', async () => {
    grantAdmin.mockImplementation(() => respond({ success: true }));
    await render();
    await clickOption('Make admin');
    expect(grantAdmin).toHaveBeenCalledWith('priya', 'tok');
    expect(getUsers).toHaveBeenCalledTimes(2);
    expect(toasts()).toEqual([]);
  });

  it('Activate shows no success toast', async () => {
    setUserActive.mockImplementation(() => respond({ success: true }));
    await render({ active: false });
    await clickOption('Activate');
    expect(setUserActive).toHaveBeenCalledWith('priya', true, 'tok');
    expect(toasts()).toEqual([]);
  });

  it('Force logout keeps its success toast (nothing in the row changes)', async () => {
    revokeSessions.mockImplementation(() => respond({ success: true }));
    await render();
    await clickOption('Force logout');
    expect(toasts()).toEqual([
      { variant: 'success', message: 'Sessions revoked for priya' },
    ]);
  });

  it('a failed unconfirmed action shows a destructive toast', async () => {
    grantAdmin.mockImplementation(() =>
      respond({ success: false, message: 'Not allowed' }, false),
    );
    await render();
    await clickOption('Make admin');
    expect(toasts()).toEqual([
      { variant: 'destructive', message: 'Not allowed' },
    ]);
  });

  it('a confirmed Revoke admin shows no success toast', async () => {
    revokeAdmin.mockImplementation(() => respond({ success: true }));
    await render({}, ['priya']);
    await clickOption('Revoke admin');
    await expect(submitConfirm()).resolves.toBeUndefined();
    expect(revokeAdmin).toHaveBeenCalledWith('priya', 'tok');
    expect(toasts()).toEqual([]);
  });

  it('a confirmed Deactivate shows no success toast', async () => {
    setUserActive.mockImplementation(() => respond({ success: true }));
    await render();
    await clickOption('Deactivate');
    await expect(submitConfirm()).resolves.toBeUndefined();
    expect(setUserActive).toHaveBeenCalledWith('priya', false, 'tok');
    expect(toasts()).toEqual([]);
  });

  it('a failed confirmed action stays in the dialog, no toast', async () => {
    setUserActive.mockImplementation(() =>
      respond({ success: false, message: 'Last admin' }, false),
    );
    await render();
    await clickOption('Deactivate');
    await expect(submitConfirm()).rejects.toThrow('Last admin');
    expect(confirmProps.current?.error).toBe('Last admin');
    expect(toasts()).toEqual([]);
  });
});
