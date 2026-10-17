import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import type { RootState } from '../store';
import reducer, {
  appendConversations,
  clearRoles,
  CONVERSATIONS_PAGE_SIZE,
  removeConversation,
  renameConversation,
  setConversationsHead,
  setConversationsLoading,
  prefListenerMiddleware,
  selectIsAdmin,
  selectRoles,
  selectRolesResolved,
  selectTtsAvailable,
  setAuthRequired,
  setRoles,
  setSourceDocs,
  setSpeechAvailability,
  setToken,
} from './preferenceSlice';

const baseState = () => reducer(undefined, { type: '@@INIT' });

describe('preference roles reducer', () => {
  it('starts unresolved with no roles', () => {
    const state = baseState();
    expect(state.roles).toEqual([]);
    expect(state.rolesResolved).toBe(false);
  });

  it('setRoles stores roles and marks resolved', () => {
    const state = reducer(baseState(), setRoles(['user', 'admin']));
    expect(state.roles).toEqual(['user', 'admin']);
    expect(state.rolesResolved).toBe(true);
  });

  it('clearRoles resets roles and resolution', () => {
    const granted = reducer(baseState(), setRoles(['admin']));
    const state = reducer(granted, clearRoles());
    expect(state.roles).toEqual([]);
    expect(state.rolesResolved).toBe(false);
  });
});

const stateWith = (roles: string[], rolesResolved = true) =>
  ({ preference: { roles, rolesResolved } }) as unknown as RootState;

describe('roles selectors', () => {
  it('selectIsAdmin is true only when admin is present', () => {
    expect(selectIsAdmin(stateWith(['admin', 'user']))).toBe(true);
    expect(selectIsAdmin(stateWith(['user']))).toBe(false);
    expect(selectIsAdmin(stateWith([]))).toBe(false);
  });

  it('selectRoles and selectRolesResolved read state', () => {
    expect(selectRoles(stateWith(['user']))).toEqual(['user']);
    expect(selectRolesResolved(stateWith(['user'], false))).toBe(false);
  });
});

const sourceDoc = (overrides: Partial<Doc>): Doc => ({
  name: 'doc',
  date: '2026-01-01',
  model: 'm',
  ...overrides,
});

const storeWithListener = () =>
  configureStore({
    reducer: { preference: reducer },
    middleware: (getDefault) =>
      getDefault().prepend(prefListenerMiddleware.middleware),
  });

describe('setSourceDocs reconciler', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('prunes a stored selection when the source list comes back empty', () => {
    const stored = [sourceDoc({ id: 'gone', name: 'Deleted' })];
    localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(stored));
    const store = storeWithListener();

    store.dispatch(setSourceDocs([]));

    expect(store.getState().preference.selectedDocs).toEqual([]);
    expect(localStorage.getItem('DocsGPTRecentDocs')).toBeNull();
  });

  it('keeps a stored selection that is still in the list', () => {
    const kept = sourceDoc({ id: 'kept', name: 'Kept' });
    localStorage.setItem('DocsGPTRecentDocs', JSON.stringify([kept]));
    const store = storeWithListener();

    store.dispatch(setSourceDocs([kept, sourceDoc({ id: 'other' })]));

    expect(store.getState().preference.selectedDocs).toEqual([kept]);
  });

  it('leaves the selection alone while the list has not loaded', () => {
    const stored = [sourceDoc({ id: 'pending' })];
    localStorage.setItem('DocsGPTRecentDocs', JSON.stringify(stored));
    const store = storeWithListener();

    store.dispatch(setSourceDocs(null));

    expect(localStorage.getItem('DocsGPTRecentDocs')).not.toBeNull();
  });
});

describe('conversation list paging', () => {
  const conv = (i: number) => ({
    id: `c${i}`,
    name: `chat ${i}`,
    agent_id: null,
    // Newest first: a higher index is older.
    date: new Date(Date.UTC(2026, 8, 30) - i * 60_000).toISOString(),
  });
  const range = (from: number, n: number) =>
    Array.from({ length: n }, (_, i) => conv(from + i));
  const ids = (state: ReturnType<typeof baseState>) =>
    (state.conversations.data ?? []).map((c) => c.id);
  const full = CONVERSATIONS_PAGE_SIZE;

  it('a full newest page may have older chats; a short one is the whole list', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    expect(state.conversations.hasMore).toBe(true);
    state = reducer(state, setConversationsHead(range(0, 3)));
    expect(ids(state)).toEqual(['c0', 'c1', 'c2']);
    expect(state.conversations.hasMore).toBe(false);
  });

  it('appends an older page without repeats, and a short one ends the list', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    state = reducer(state, appendConversations(range(full - 1, 10)));
    expect(ids(state)).toHaveLength(full + 9);
    expect(new Set(ids(state)).size).toBe(full + 9);
    expect(state.conversations.hasMore).toBe(false);
  });

  // A new chat or a rename re-fetches the newest page; the older chats
  // already scrolled to stay, so the list doesn't snap back to 30.
  it('a refreshed newest page keeps the older chats already loaded', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    state = reducer(state, appendConversations(range(full, full)));
    const fresh = [{ ...conv(-1), id: 'new' }, ...range(0, full - 1)];
    state = reducer(state, setConversationsHead(fresh));
    expect(ids(state)[0]).toBe('new');
    expect(ids(state)).toHaveLength(2 * full + 1);
    expect(state.conversations.hasMore).toBe(true);
  });

  it('removes a deleted chat wherever it is in the list', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    state = reducer(state, appendConversations(range(full, 5)));
    state = reducer(state, removeConversation(`c${full + 2}`));
    expect(ids(state)).not.toContain(`c${full + 2}`);
    expect(ids(state)).toHaveLength(full + 4);
  });

  // Deleting refreshes the newest page; flagging the list as loading must not
  // put back a chat removed past the first page, or the merge keeps it.
  it('a deleted older chat stays gone through the refresh that follows', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    state = reducer(state, appendConversations(range(full, full)));
    const gone = `c${full + 15}`;
    state = reducer(state, removeConversation(gone));
    state = reducer(state, setConversationsLoading(true));
    expect(state.conversations.loading).toBe(true);
    state = reducer(state, setConversationsHead(range(0, full)));
    expect(ids(state)).not.toContain(gone);
    expect(ids(state)).toHaveLength(2 * full - 1);
    expect(state.conversations.loading).toBe(false);
  });

  // A rename keeps the chat's date, so a chat past the first page is never
  // in the refreshed newest page; the new name has to be written here.
  it('renames a chat wherever it is in the list', () => {
    let state = reducer(baseState(), setConversationsHead(range(0, full)));
    state = reducer(state, appendConversations(range(full, 5)));
    const id = `c${full + 3}`;
    state = reducer(state, renameConversation({ id, name: 'Renamed' }));
    state = reducer(state, setConversationsHead(range(0, full)));
    const chat = state.conversations.data?.find((c) => c.id === id);
    expect(chat?.name).toBe('Renamed');
    expect(ids(state)).toHaveLength(full + 5);
  });
});

describe('text-to-speech availability', () => {
  const ttsFor = (actions: Parameters<typeof reducer>[1][]) =>
    selectTtsAvailable({
      preference: actions.reduce(reducer, baseState()),
    } as RootState);

  it('is offered on an instance without auth', () => {
    expect(ttsFor([setAuthRequired(false)])).toBe(true);
  });

  it('is hidden from a signed-out viewer when the server requires auth', () => {
    expect(ttsFor([setAuthRequired(true)])).toBe(false);
  });

  it('is offered to a signed-in user when the server requires auth', () => {
    expect(ttsFor([setAuthRequired(true), setToken('tok')])).toBe(true);
  });

  it('stays hidden when the server has it switched off', () => {
    expect(
      ttsFor([
        setToken('tok'),
        setSpeechAvailability({ tts: false, stt: true }),
      ]),
    ).toBe(false);
  });
});
