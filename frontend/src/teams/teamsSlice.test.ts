const remove = vi.fn();
const list = vi.fn();
const setOutsidePolicy = vi.fn();

vi.mock('../api/services/teamsService', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  default: {
    remove: (...args: unknown[]) => remove(...args),
    list: (...args: unknown[]) => list(...args),
    setOutsidePolicy: (...args: unknown[]) => setOutsidePolicy(...args),
  },
}));

import { configureStore } from '@reduxjs/toolkit';

import { teamErrorMessage, TeamsApiError } from '../api/services/teamsService';
import workspaceReducer, {
  loadWorkspaces,
  outsidePolicyChanged,
  selectCurrentOutsidePolicy,
  switchWorkspace,
} from '../workspace/workspaceSlice';
import { errorMessage } from './accessSettings';
import reducer, {
  deleteTeam,
  loadTeams,
  setTeamOutsidePolicy,
  Team,
} from './teamsSlice';

const team: Team = { id: 't1', name: 'Ops', slug: 'ops', owner_id: 'u1' };

const makeStore = () =>
  configureStore({
    reducer: { teams: reducer },
    preloadedState: {
      teams: {
        teams: [team],
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

  it("surfaces the server's reason through unwrap()", async () => {
    // unwrap() rethrows a serialized plain object, not the Error instance.
    remove.mockRejectedValue(
      Object.assign(new Error('Only the owner can delete'), {
        name: 'TeamsApiError',
      }),
    );
    const store = makeStore();
    const rejection = await store
      .dispatch(deleteTeam({ id: 't1', token: null }))
      .unwrap()
      .catch((error: unknown) => error);
    expect(errorMessage(rejection, 'fallback')).toBe(
      'Only the owner can delete',
    );
  });

  it('keeps the fallback for a non-teams rejection', async () => {
    remove.mockRejectedValue(new Error('network down'));
    const store = makeStore();
    const rejection = await store
      .dispatch(deleteTeam({ id: 't1', token: null }))
      .unwrap()
      .catch((error: unknown) => error);
    expect(errorMessage(rejection, 'fallback')).toBe('fallback');
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

describe("a team's outside policy", () => {
  const ops: Team = {
    ...team,
    outside_policy: 'admins',
    can_set_outside_policy: true,
  };
  const withWorkspace = () =>
    configureStore({
      reducer: { teams: reducer, workspace: workspaceReducer },
      preloadedState: {
        teams: { teams: [ops], loading: false, error: null },
      },
    });

  beforeEach(() => {
    setOutsidePolicy.mockReset();
  });

  it('updates the team and its workspace row once the server agrees', async () => {
    setOutsidePolicy.mockResolvedValue({
      success: true,
      changed: true,
      outside_policy: 'locked',
      can_set_outside_policy: false,
    });
    const store = withWorkspace();
    store.dispatch({
      type: loadWorkspaces.fulfilled.type,
      payload: [
        {
          id: 't1',
          kind: 'team',
          name: 'Ops',
          role: 'admin',
          outside_policy: 'admins',
        },
      ],
      meta: { requestId: null },
    });
    store.dispatch(switchWorkspace('t1'));
    const result = await store
      .dispatch(
        setTeamOutsidePolicy({ teamId: 't1', policy: 'locked', token: null }),
      )
      .unwrap();
    expect(setOutsidePolicy).toHaveBeenCalledWith('t1', 'locked', null);
    expect(result.changed).toBe(true);
    expect(store.getState().teams.teams[0]).toMatchObject({
      outside_policy: 'locked',
      can_set_outside_policy: false,
    });
    expect(selectCurrentOutsidePolicy(store.getState())).toBe('locked');
  });

  it('keeps the policy and the refusal code when the server says no', async () => {
    setOutsidePolicy.mockRejectedValue(
      new TeamsApiError(
        403,
        "Only the team's Owner can unlock it",
        'policy_owner_only',
      ),
    );
    const store = withWorkspace();
    const rejection = await store
      .dispatch(
        setTeamOutsidePolicy({ teamId: 't1', policy: 'admins', token: null }),
      )
      .unwrap()
      .catch((error: unknown) => error);
    expect(teamErrorMessage((key: string) => key, rejection, 'fallback')).toBe(
      'settings.teams.errors.policyOwnerOnly',
    );
    expect(store.getState().teams.teams[0].outside_policy).toBe('admins');
  });

  it('takes a policy read elsewhere (the team page) into the team row', () => {
    const store = withWorkspace();
    store.dispatch(
      outsidePolicyChanged({
        teamId: 't1',
        outside_policy: 'editors',
        can_set_outside_policy: true,
      }),
    );
    expect(store.getState().teams.teams[0].outside_policy).toBe('editors');
  });
});
