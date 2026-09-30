import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const getQuotas = vi.fn();
const searchTeams = vi.fn();
vi.mock('../api/services/adminService', () => ({
  default: { getQuotas: (...a: unknown[]) => getQuotas(...a) },
}));
vi.mock('../api/services/teamsService', () => ({
  default: { searchAdminTeams: (...a: unknown[]) => searchTeams(...a) },
}));

import { prefSlice } from '../preferences/preferenceSlice';
import Quotas from './Quotas';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const policy = (i: number, scope: 'team' | 'user') => ({
  scope,
  subject_id: `${scope}-${i}`,
  bucket: 'all',
  enabled: true,
  token_limit: 1000,
  token_unlimited: false,
  cost_limit_usd: null,
  cost_unlimited: true,
  note: null,
  updated_at: null,
  team_name: scope === 'team' ? `Team ${i}` : undefined,
  member_count: 3,
});

const quotas = (teamsTotal: number, usersTotal: number) => ({
  json: async () => ({
    success: true,
    period: 'month',
    resets_at: '2026-10-01T00:00:00Z',
    instance: [],
    teams: Array.from({ length: Math.min(25, teamsTotal) }, (_, i) =>
      policy(i, 'team'),
    ),
    users: Array.from({ length: Math.min(25, usersTotal) }, (_, i) =>
      policy(i, 'user'),
    ),
    unpriced_models: [],
    teams_total: teamsTotal,
    users_total: usersTotal,
  }),
});

describe('Quotas paging', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getQuotas.mockReset();
    searchTeams.mockReset().mockResolvedValue({ teams: [] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    const store = configureStore({
      reducer: { preference: prefSlice.reducer },
    });
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Quotas />
        </Provider>,
      ),
    );
    for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
  };
  const pagers = () =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="pagination-full"]'),
    );

  it('asks for the first page of each table, 25 rows each', async () => {
    getQuotas.mockResolvedValue(quotas(2, 1));
    await render();
    expect(getQuotas.mock.calls[0][1]).toEqual({
      teamsPage: 1,
      usersPage: 1,
      pageSize: 25,
      teamsQ: '',
      usersQ: '',
    });
    // Small tables: no search and no pager, as before.
    expect(
      container.querySelector('input[placeholder="Search teams"]'),
    ).toBeNull();
    expect(pagers()).toHaveLength(0);
  });

  it('a long table gets its own search and pager', async () => {
    getQuotas.mockResolvedValue(quotas(57, 64));
    await render();
    expect(
      container.querySelector('input[placeholder="Search teams"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('input[placeholder="Search users"]'),
    ).not.toBeNull();
    expect(pagers().map((p) => p.textContent)).toEqual([
      expect.stringContaining('1–25 of 57 teams'),
      expect.stringContaining('1–25 of 64 users'),
    ]);
    await act(async () =>
      pagers()[1]
        .querySelector<HTMLButtonElement>(
          '[aria-label="pagination.goToPage"]:not([aria-current])',
        )!
        .click(),
    );
    for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
    expect(getQuotas.mock.lastCall![1]).toMatchObject({
      teamsPage: 1,
      usersPage: 2,
    });
  });

  it('picks a team without an allowance by searching the server', async () => {
    getQuotas.mockResolvedValue(quotas(2, 1));
    await render();
    const picker =
      container.querySelector<HTMLButtonElement>('[role="combobox"]')!;
    expect(picker.textContent).toContain('Choose a team');
    await act(async () => picker.click());
    for (let i = 0; i < 5; i += 1) await act(async () => Promise.resolve());
    expect(searchTeams).toHaveBeenCalledWith(null, {
      q: '',
      withoutQuota: true,
      limit: 20,
    });
  });
});
