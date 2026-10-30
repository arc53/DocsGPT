import {
  configureStore,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/services/activityService', () => ({
  default: { now: vi.fn(), stopMessage: vi.fn() },
}));
vi.mock('../backgroundJobs/usePageVisible', () => ({
  usePageVisible: () => true,
}));

import activityService from '../api/services/activityService';
import reducer, { loadActivityNow, resetActivity } from './activitySlice';
import type { NowSnapshot } from './types';
import useActivityLoader from './useActivityLoader';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const snapshot = (title: string): NowSnapshot => ({
  running: [{ kind: 'chat', id: 'm1', title, conversation_id: 'c1' }],
  needs_you: [],
  up_next: [],
  approval_conversations: [],
  failed_conversations: [],
  stats: { next_24h: 0, failed_24h: 0 },
});

const preference = createSlice({
  name: 'preference',
  initialState: { token: 'token-a' as string | null },
  reducers: {
    setToken: (state, action: PayloadAction<string | null>) => {
      state.token = action.payload;
    },
  },
});

function Loader() {
  useActivityLoader();
  return null;
}

describe('useActivityLoader', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
  });

  it("forgets the last account's activity when the token changes", async () => {
    const store = configureStore({
      reducer: { activity: reducer, preference: preference.reducer },
    });
    vi.mocked(activityService.now).mockResolvedValueOnce(snapshot('Mine'));
    await act(async () =>
      root.render(
        <Provider store={store}>
          <Loader />
        </Provider>,
      ),
    );
    expect(store.getState().activity.now?.running[0].title).toBe('Mine');

    // The next account's snapshot is still on its way.
    vi.mocked(activityService.now).mockReturnValueOnce(new Promise(() => {}));
    await act(async () =>
      store.dispatch(preference.actions.setToken('token-b')),
    );
    expect(store.getState().activity.now).toBeNull();
  });
});

describe('resetActivity', () => {
  it('drops the answer to a fetch sent before it', () => {
    let state = reducer(undefined, loadActivityNow.pending('old', 'poll'));
    state = reducer(state, resetActivity());
    state = reducer(
      state,
      loadActivityNow.fulfilled(snapshot('Theirs'), 'old', 'poll'),
    );
    expect(state.now).toBeNull();
  });
});
