const remove = vi.fn();
const list = vi.fn();

vi.mock('../api/services/teamsService', () => ({
  default: {
    remove: (...args: unknown[]) => remove(...args),
    list: (...args: unknown[]) => list(...args),
  },
}));

import { configureStore } from '@reduxjs/toolkit';

import reducer, { deleteTeam, loadTeams, Team } from './teamsSlice';

const team: Team = { id: 't1', name: 'Ops', slug: 'ops', owner_id: 'u1' };

const makeStore = () =>
  configureStore({
    reducer: { teams: reducer },
    preloadedState: {
      teams: {
        teams: [team],
        currentTeamId: null,
        loading: false,
        error: null,
      },
    },
  });

describe('teamsSlice', () => {
  beforeEach(() => {
    remove.mockReset();
    list.mockReset();
  });

  it('keeps the team when the delete is rejected (403)', async () => {
    remove.mockRejectedValue(new Error('Only the owner can delete'));
    const store = makeStore();
    const result = await store.dispatch(deleteTeam({ id: 't1', token: null }));
    expect(result.type).toBe('teams/delete/rejected');
    expect(store.getState().teams.teams).toHaveLength(1);
  });

  it('keeps the team when a 2xx body says success:false', async () => {
    remove.mockResolvedValue({ success: false, message: 'nope' });
    const store = makeStore();
    await store.dispatch(deleteTeam({ id: 't1', token: null }));
    expect(store.getState().teams.teams).toHaveLength(1);
  });

  it('removes the team on success', async () => {
    remove.mockResolvedValue({ success: true });
    const store = makeStore();
    await store.dispatch(deleteTeam({ id: 't1', token: null }));
    expect(store.getState().teams.teams).toHaveLength(0);
  });

  it('records a load failure instead of an empty list', async () => {
    list.mockRejectedValue(new Error('boom'));
    const store = makeStore();
    await store.dispatch(loadTeams({ token: null }));
    expect(store.getState().teams.error).toBe('boom');
    expect(store.getState().teams.teams).toHaveLength(1);
  });
});
