import { describe, expect, it } from 'vitest';

import type { RootState } from '../store';
import reducer, {
  clearRoles,
  selectIsAdmin,
  selectRoles,
  selectRolesResolved,
  setRoles,
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
