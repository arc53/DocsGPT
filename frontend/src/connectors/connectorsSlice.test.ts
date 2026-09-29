import reducer, {
  loadConnectors,
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
