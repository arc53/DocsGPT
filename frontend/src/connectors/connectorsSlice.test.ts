import connectorsService from '../api/services/connectorsService';
import {
  PERSONAL_WORKSPACE,
  setRequestWorkspace,
} from '../workspace/requestWorkspace';
import reducer, {
  connectionNeedsSignIn,
  loadConnectors,
  loadTeamConnectors,
  reloadConnectors,
  selectConnectionsNeedAttention,
  selectConnectorsSettled,
  selectPickableConnections,
  selectStartedSyncs,
  selectTeamConnectors,
  selectTeamConnections,
  selectWorkspaceConnections,
  selectWorkspaceConnectorCatalog,
  selectWorkspaceConnectorsLoaded,
  syncForgotten,
  syncStarted,
  type ConnectorsState,
} from './connectorsSlice';
import type { Connection, ConnectorDefinition } from './types';

const arg = { token: null };
const connection = (id: string) => ({ id }) as unknown as Connection;
const payload = (ids: string[]) => ({
  catalog: [],
  connections: ids.map(connection),
});

const pending = (state: ConnectorsState | undefined, requestId: string) =>
  reducer(state, loadConnectors.pending(requestId, arg));

describe('connectorsSlice loadConnectors', () => {
  it('keeps the newer response when an older one arrives last', () => {
    let state = pending(undefined, 'old');
    state = pending(state, 'new');
    state = reducer(
      state,
      loadConnectors.fulfilled(payload(['after-connect']), 'new', arg),
    );
    state = reducer(
      state,
      loadConnectors.fulfilled(payload(['before-connect']), 'old', arg),
    );
    expect(state.connections.map((c) => c.id)).toEqual(['after-connect']);
  });

  it('stays unloaded while the latest request is still running', () => {
    let state = pending(undefined, 'old');
    state = pending(state, 'new');
    state = reducer(
      state,
      loadConnectors.fulfilled(payload(['stale']), 'old', arg),
    );
    expect(state.loaded).toBe(false);
    expect(state.connections).toEqual([]);
  });

  it('ignores the failure of an older request', () => {
    let state = pending(undefined, 'old');
    state = pending(state, 'new');
    state = reducer(
      state,
      loadConnectors.rejected(new Error('boom'), 'old', arg),
    );
    expect(state.failed).toBe(false);
    state = reducer(
      state,
      loadConnectors.rejected(new Error('boom'), 'new', arg),
    );
    expect(state.failed).toBe(true);
  });

  // A reload clears `failed` while it runs; what reads the list once it has
  // answered (the empty chat's suggestions) shouldn't blink meanwhile.
  it('is settled once any load has answered, through later reloads', () => {
    let state = pending(undefined, '1');
    expect(selectConnectorsSettled({ connectors: state })).toBe(false);
    state = reducer(
      state,
      loadConnectors.rejected(new Error('boom'), '1', arg),
    );
    state = pending(state, '2');
    expect(state.failed).toBe(false);
    expect(selectConnectorsSettled({ connectors: state })).toBe(true);
    let listed = pending(undefined, '1');
    listed = reducer(listed, loadConnectors.fulfilled(payload([]), '1', arg));
    listed = pending(listed, '2');
    expect(selectConnectorsSettled({ connectors: listed })).toBe(true);
    // An older request's answer doesn't count.
    let stale = pending(undefined, 'old');
    stale = pending(stale, 'new');
    stale = reducer(
      stale,
      loadConnectors.rejected(new Error('boom'), 'old', arg),
    );
    expect(selectConnectorsSettled({ connectors: stale })).toBe(false);
  });
});

// One definition for every surface (Knowledge, Tools, pickers, the nav dot),
// matching the backend's "reconnect" card state: an expired or failing
// sign-in. A disconnect is the user's own act and warns nowhere.
describe('connectionNeedsSignIn', () => {
  it.each([
    ['reconnect_needed', true],
    ['error', true],
    ['disconnected', false],
    ['connected', false],
    ['pending', false],
  ])('%s → %s', (status, expected) => {
    expect(connectionNeedsSignIn({ status })).toBe(expected);
  });

  it('is false for no connection', () => {
    expect(connectionNeedsSignIn(undefined)).toBe(false);
    expect(connectionNeedsSignIn(null)).toBe(false);
  });

  it('lights the nav dot with the same rule', () => {
    const state = (statuses: string[]) => ({
      connectors: {
        ...reducer(undefined, { type: 'init' }),
        connections: statuses.map(
          (status, i) => ({ id: String(i), status }) as unknown as Connection,
        ),
      },
    });
    expect(selectConnectionsNeedAttention(state(['disconnected']))).toBe(false);
    expect(selectConnectionsNeedAttention(state(['connected', 'error']))).toBe(
      true,
    );
  });
});

describe('connectorsSlice syncStarted', () => {
  const sync = (id: string, name: string) => ({
    id,
    name,
    connectionId: 'conn-1',
    startedAt: '2026-10-23T10:00:00Z',
  });

  it('keeps one entry per source, the latest start', () => {
    let state = reducer(
      undefined,
      syncStarted([sync('a', 'A'), sync('b', 'B')]),
    );
    state = reducer(state, syncStarted([sync('a', 'A again')]));
    expect(selectStartedSyncs({ connectors: state })).toEqual([
      sync('b', 'B'),
      sync('a', 'A again'),
    ]);
  });

  it('forgets the syncs it is told to', () => {
    let state = reducer(
      undefined,
      syncStarted([sync('a', 'A'), sync('b', 'B'), sync('c', 'C')]),
    );
    state = reducer(state, syncForgotten(['a', 'c', 'unknown']));
    expect(selectStartedSyncs({ connectors: state })).toEqual([sync('b', 'B')]);
  });

  it('reads none from a state that never had any', () => {
    expect(
      selectStartedSyncs({
        connectors: { startedSyncs: undefined } as ConnectorsState,
      }),
    ).toEqual([]);
  });
});

describe('team connections, kept per team', () => {
  const teamArg = (teamId: string) => ({ token: null, teamId });
  const teamPending = (
    state: ConnectorsState | undefined,
    requestId: string,
    teamId = 't1',
  ) => reducer(state, loadTeamConnectors.pending(requestId, teamArg(teamId)));
  const teamRow = (id: string, extra: Partial<Connection> = {}) =>
    ({ id, owner: 'team', status: 'connected', ...extra }) as Connection;
  const answer = (connections: Connection[], catalog: string[] = []) => ({
    catalog: catalog.map((key) => ({ key }) as ConnectorDefinition),
    connections,
  });
  const root = (connectors: ConnectorsState, current = 't1') => ({
    connectors,
    workspace: { current },
  });

  afterEach(() => {
    vi.restoreAllMocks();
    setRequestWorkspace(PERSONAL_WORKSPACE, 0);
  });

  it("files each team's answer under that team, apart from the caller's own", () => {
    let state = reducer(
      pending(undefined, 'p'),
      loadConnectors.fulfilled(payload(['mine']), 'p', arg),
    );
    state = teamPending(state, 'a', 't1');
    state = teamPending(state, 'b', 't2');
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('drive-1')], ['google_drive']),
        'a',
        teamArg('t1'),
      ),
    );
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('drive-2')]),
        'b',
        teamArg('t2'),
      ),
    );
    expect(state.connections.map((c) => c.id)).toEqual(['mine']);
    expect(
      selectTeamConnections({ connectors: state }, 't1').map((c) => c.id),
    ).toEqual(['drive-1']);
    expect(
      selectTeamConnections({ connectors: state }, 't2').map((c) => c.id),
    ).toEqual(['drive-2']);
    expect(selectTeamConnectors({ connectors: state }, 't1')).toMatchObject({
      loaded: true,
      failed: false,
    });
  });

  it("keeps a team's newer answer when an older one arrives last", () => {
    let state = teamPending(undefined, 'old');
    state = teamPending(state, 'new');
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('after')]),
        'new',
        teamArg('t1'),
      ),
    );
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('before')]),
        'old',
        teamArg('t1'),
      ),
    );
    state = reducer(
      state,
      loadTeamConnectors.rejected(new Error('x'), 'old', teamArg('t1')),
    );
    expect(
      selectTeamConnections({ connectors: state }, 't1').map((c) => c.id),
    ).toEqual(['after']);
    expect(selectTeamConnectors({ connectors: state }, 't1').failed).toBe(
      false,
    );
  });

  it('marks only the failing team as failed and keeps its last list', () => {
    let state = teamPending(undefined, '1');
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('kept')]),
        '1',
        teamArg('t1'),
      ),
    );
    state = teamPending(state, '2');
    state = reducer(
      state,
      loadTeamConnectors.rejected(new Error('x'), '2', teamArg('t1')),
    );
    const entry = selectTeamConnectors({ connectors: state }, 't1');
    expect(entry.failed).toBe(true);
    expect(entry.connections.map((c) => c.id)).toEqual(['kept']);
    expect(selectTeamConnectors({ connectors: state }, 't2')).toMatchObject({
      loaded: false,
      connections: [],
    });
  });

  it("reads the current team's list in a team and the caller's own in Personal", () => {
    let state = reducer(
      pending(undefined, 'p'),
      loadConnectors.fulfilled(
        { catalog: [{ key: 'own' } as ConnectorDefinition], connections: [] },
        'p',
        arg,
      ),
    );
    state = teamPending(state, 'a');
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([teamRow('team-row')], ['team']),
        'a',
        teamArg('t1'),
      ),
    );
    expect(
      selectWorkspaceConnections(root(state, 't1')).map((c) => c.id),
    ).toEqual(['team-row']);
    expect(
      selectWorkspaceConnectorCatalog(root(state, 't1')).map((c) => c.key),
    ).toEqual(['team']);
    expect(selectWorkspaceConnectorsLoaded(root(state, 't1'))).toBe(true);
    expect(
      selectWorkspaceConnectorCatalog(root(state, PERSONAL_WORKSPACE)).map(
        (c) => c.key,
      ),
    ).toEqual(['own']);
    // A team whose list hasn't answered yet shows nothing, never Personal's.
    expect(selectWorkspaceConnections(root(state, 't9'))).toEqual([]);
    expect(selectWorkspaceConnectorsLoaded(root(state, 't9'))).toBe(false);
  });

  it('offers a team picker only the connections the caller may pick from', () => {
    let state = reducer(
      pending(undefined, 'p'),
      loadConnectors.fulfilled(payload(['mine']), 'p', arg),
    );
    state = teamPending(state, 'a');
    state = reducer(
      state,
      loadTeamConnectors.fulfilled(
        answer([
          teamRow('mine-for-team', { can_pick: true }),
          teamRow('lenas', { can_pick: false }),
          teamRow('paused', { can_pick: false, status: 'paused' }),
        ]),
        'a',
        teamArg('t1'),
      ),
    );
    expect(
      selectPickableConnections(root(state, 't1')).map((c) => c.id),
    ).toEqual(['mine-for-team']);
    expect(
      selectPickableConnections(root(state, PERSONAL_WORKSPACE)).map(
        (c) => c.id,
      ),
    ).toEqual(['mine']);
    // Same answer, same array: a component reading it doesn't re-render.
    expect(selectPickableConnections(root(state, 't1'))).toBe(
      selectPickableConnections(root(state, 't1')),
    );
  });

  it("asks for the team's list with owner=team, sent to that team", async () => {
    const catalog = vi
      .spyOn(connectorsService, 'getCatalog')
      .mockResolvedValue({ success: true, connectors: [] });
    const list = vi
      .spyOn(connectorsService, 'listConnections')
      .mockResolvedValue({ success: true, connections: [teamRow('r')] });
    const dispatch = vi.fn();
    const result = await loadTeamConnectors(teamArg('t1'))(
      dispatch,
      () => ({}),
      undefined,
    );
    const options = { owner: 'team', workspace: 't1' };
    expect(catalog).toHaveBeenCalledWith(null, options);
    expect(list).toHaveBeenCalledWith(null, options);
    expect(result.type).toBe(loadTeamConnectors.fulfilled.type);
  });

  it('fails the team load on a refusal (a Viewer of a team they left)', async () => {
    vi.spyOn(connectorsService, 'getCatalog').mockResolvedValue({
      success: true,
      connectors: [],
    });
    vi.spyOn(connectorsService, 'listConnections').mockResolvedValue({
      success: false,
      error: 'workspace_not_found',
    });
    const result = await loadTeamConnectors(teamArg('t1'))(
      vi.fn(),
      () => ({}),
      undefined,
    );
    expect(result.type).toBe(loadTeamConnectors.rejected.type);
  });

  it("reloads the caller's own list, and the team's while in one", async () => {
    vi.spyOn(connectorsService, 'getCatalog').mockResolvedValue({
      success: true,
      connectors: [],
    });
    vi.spyOn(connectorsService, 'listConnections').mockResolvedValue({
      success: true,
      connections: [],
    });
    const types = async () => {
      const dispatch = vi.fn((action: unknown) =>
        typeof action === 'function'
          ? action(dispatch, () => ({}), undefined)
          : action,
      );
      await reloadConnectors({ token: null })(dispatch, () => ({}), undefined);
      return dispatch.mock.calls
        .map(([action]) => (action as { type?: string }).type)
        .filter(
          (type) =>
            type?.endsWith('/pending') && type !== 'connectors/reload/pending',
        );
    };
    expect(await types()).toEqual(['connectors/load/pending']);
    setRequestWorkspace('t1', 1);
    expect(await types()).toEqual([
      'connectors/load/pending',
      'connectors/loadTeam/pending',
    ]);
  });
});
