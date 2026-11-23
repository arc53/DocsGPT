import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

// A JWT whose payload is {"sub":"me"}.
const TOKEN = `x.${btoa(JSON.stringify({ sub: 'me' }))}.y`;

const mockState = {
  preference: { token: TOKEN },
  workspace: {
    current: 'personal',
    workspaces: [
      { id: 'personal', kind: 'personal', name: 'Personal' },
      {
        id: 't1',
        kind: 'team',
        name: 'Operations',
        role: 'admin',
        chat_export: true,
      } as Record<string, unknown>,
    ],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  },
};

const mockDispatch = vi.fn((action: unknown) => {
  void action;
  return { unwrap: () => Promise.resolve() };
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

vi.mock('../../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/teamsService')>()),
  default: {
    update: vi.fn(),
    listMembers: () => Promise.resolve({ members: [], total: 0 }),
    transferOwner: vi.fn(),
  },
}));

const exportTeamChats = vi.fn();
vi.mock('../../api/services/payerService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/services/payerService')>()),
  default: {
    exportTeamChats: (...a: unknown[]) => exportTeamChats(...a),
  },
}));

const downloadBlob = vi.fn();
vi.mock('../../utils/browserUtils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../utils/browserUtils')>()),
  downloadBlob: (...a: unknown[]) => downloadBlob(...a),
}));

import { PayerApiError } from '../../api/services/payerService';
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
  owner_id: 'lena',
  is_owner: false,
};

const teamRow = () =>
  mockState.workspace.workspaces[1] as Record<string, unknown>;

describe('SettingsTab: Export chats', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    teamRow().chat_export = true;
    exportTeamChats.mockReset().mockResolvedValue({
      blob: new Blob(['{}\n']),
      filename: 'docsgpt-operations-chats-2026-11-16.ndjson',
    });
    downloadBlob.mockReset();
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

  const render = async (role: 'owner' | 'admin' | 'editor' = 'admin') => {
    act(() => {
      root.render(
        <MemoryRouter>
          <SettingsTab team={TEAM} role={role} />
        </MemoryRouter>,
      );
    });
    await flush();
  };

  const exportButton = () =>
    Array.from(body().querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === 'payer.team.export.action',
    );

  const toasts = () =>
    mockDispatch.mock.calls
      .map(([action]) => action as { payload?: { message?: string } })
      .filter((a) => a?.payload?.message)
      .map((a) => a.payload!.message);

  it('shows the Export row to an admin when the setting is on', async () => {
    await render('admin');
    expect(body().textContent).toContain('payer.team.export.title');
    expect(body().textContent).toContain('payer.team.export.description');
    expect(exportButton()).toBeDefined();
  });

  it('shows it to the owner too', async () => {
    await render('owner');
    expect(exportButton()).toBeDefined();
  });

  it('has no Export row while the setting is off', async () => {
    teamRow().chat_export = false;
    await render('admin');
    expect(body().textContent).not.toContain('payer.team.export.title');
    expect(exportButton()).toBeUndefined();
  });

  it('has no Export row below Admin', async () => {
    await render('editor');
    expect(exportButton()).toBeUndefined();
  });

  it("downloads the file under the server's name", async () => {
    await render('admin');
    act(() => exportButton()!.click());
    await flush();
    expect(exportTeamChats).toHaveBeenCalledWith('t1', TOKEN);
    expect(downloadBlob).toHaveBeenCalledWith(
      expect.any(Blob),
      'docsgpt-operations-chats-2026-11-16.ndjson',
    );
  });

  it('says a refusal in its own words', async () => {
    exportTeamChats.mockRejectedValue(
      new PayerApiError(403, 'server words', 'workspace_role_required'),
    );
    await render('admin');
    act(() => exportButton()!.click());
    await flush();
    expect(downloadBlob).not.toHaveBeenCalled();
    expect(toasts()).toContain('payer.common.errors.roleRequired');
  });

  it('says a failed export plainly', async () => {
    exportTeamChats.mockRejectedValue(new Error('network'));
    await render('admin');
    act(() => exportButton()!.click());
    await flush();
    expect(toasts()).toContain('payer.team.export.failed');
  });
});
