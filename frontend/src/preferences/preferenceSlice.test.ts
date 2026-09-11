import { configureStore } from '@reduxjs/toolkit';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Doc } from '../models/misc';
import type { RootState } from '../store';
import reducer, {
  clearRoles,
  prefListenerMiddleware,
  selectIsAdmin,
  selectRoles,
  selectRolesResolved,
  setRoles,
  setSourceDocs,
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
