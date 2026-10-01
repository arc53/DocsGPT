import reducer, {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnectionsNeedAttention,
  type ConnectorsState,
} from './connectorsSlice';
import type { Connection } from './types';

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
    expect(state.loading).toBe(false);
  });

  it('stays loading while the latest request is still running', () => {
    let state = pending(undefined, 'old');
    state = pending(state, 'new');
    state = reducer(
      state,
      loadConnectors.fulfilled(payload(['stale']), 'old', arg),
    );
    expect(state.loading).toBe(true);
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
    expect(state.loading).toBe(false);
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
