import { describe, expect, it } from 'vitest';

import { setToken } from '../preferences/preferenceSlice';
import type { UserToolType } from '../settings/types';
import reducer, {
  loadChatTools,
  selectChatTools,
  selectChatToolsLoaded,
  selectChatToolsLoading,
  setChatToolInChat,
} from './chatToolsSlice';

const tool = (id: string): UserToolType =>
  ({ id, name: id, status: false, in_chat: false }) as UserToolType;

const pending = (requestId: string, token: string | null = null) =>
  loadChatTools.pending(requestId, { token });
const fulfilled = (requestId: string, tools: UserToolType[]) =>
  loadChatTools.fulfilled(tools, requestId, { token: null });
const rejected = (requestId: string) =>
  loadChatTools.rejected(new Error('down'), requestId, { token: null });

type State = ReturnType<typeof reducer>;
const run = (...actions: Parameters<typeof reducer>[1][]): State =>
  actions.reduce<State>(reducer, reducer(undefined, { type: '' }));

describe('chatToolsSlice', () => {
  it('is loaded once a list or a failure arrives', () => {
    expect(
      selectChatToolsLoaded({ chatTools: reducer(undefined, { type: '' }) }),
    ).toBe(false);
    const listed = run(pending('1'), fulfilled('1', [tool('a')]));
    expect(listed.loaded).toBe(true);
    expect(listed.loading).toBe(false);
    const failed = run(
      pending('1'),
      fulfilled('1', [tool('a')]),
      pending('2'),
      rejected('2'),
    );
    expect(failed.tools).toEqual([tool('a')]);
    expect(failed.loaded).toBe(true);
    expect(failed.loading).toBe(false);
  });

  // Every composer loads into this one list, and a chat switch remounts
  // the composer; only the newest request, whoever made it, may answer.
  it('drops an older request answering after a newer one', () => {
    const state = run(
      pending('A'),
      pending('B'),
      fulfilled('B', [tool('newer')]),
      fulfilled('A', [tool('older')]),
    );
    expect(state.tools).toEqual([tool('newer')]);
    expect(state.loading).toBe(false);
  });

  it('stays loading until the newest request answers', () => {
    const state = run(
      pending('A'),
      pending('B'),
      fulfilled('A', [tool('older')]),
    );
    expect(state.tools).toEqual([]);
    expect(selectChatToolsLoading({ chatTools: state })).toBe(true);
    expect(run(pending('A'), pending('B'), rejected('A')).loading).toBe(true);
  });

  // The list may have been read before the switch reached the server.
  it('keeps a toggle made while a load was in flight', () => {
    const state = run(
      pending('1'),
      fulfilled('1', [tool('a')]),
      pending('2'),
      setChatToolInChat({ id: 'a', value: true, owner: true }),
      fulfilled('2', [tool('a')]),
    );
    expect(state.tools[0]).toMatchObject({ status: true, in_chat: true });
    expect(state.loading).toBe(false);
    // A load started after the toggle applies as usual.
    const next = reducer(
      reducer(state, pending('3')),
      fulfilled('3', [tool('b')]),
    );
    expect(next.tools).toEqual([tool('b')]);
  });

  // A tool created just before the toggle (its reload is the one out)
  // still shows; only the toggled tool keeps its local switch.
  it('takes the rest of the list a load answers across a toggle', () => {
    const state = run(
      pending('1'),
      fulfilled('1', [tool('a'), tool('b')]),
      pending('2'),
      setChatToolInChat({ id: 'a', value: true, owner: false }),
      fulfilled('2', [
        { ...tool('a'), name: 'renamed', status: true },
        { ...tool('b'), in_chat: true },
        tool('new'),
      ]),
    );
    expect(state.tools).toEqual([
      { ...tool('a'), name: 'renamed', status: true, in_chat: true },
      { ...tool('b'), in_chat: true },
      tool('new'),
    ]);
    expect(state.toggledSinceRequest).toEqual({});
  });

  it("sets the owner's status, and only the grantee's own switch", () => {
    let state = run(pending('1'), fulfilled('1', [tool('a'), tool('b')]));
    state = reducer(
      state,
      setChatToolInChat({ id: 'a', value: true, owner: true }),
    );
    state = reducer(
      state,
      setChatToolInChat({ id: 'b', value: true, owner: false }),
    );
    expect(state.tools[0]).toMatchObject({ status: true, in_chat: true });
    expect(state.tools[1]).toMatchObject({ status: false, in_chat: true });
  });

  // Another account's tools must not show in the picker or the suggestions.
  it('clears the list when the account changes', () => {
    const signedIn = run(
      pending('1', 'alice'),
      fulfilled('1', [tool('a')]),
      setToken('bob'),
    );
    expect(signedIn.tools).toEqual([]);
    expect(signedIn.loaded).toBe(false);
    // A load started under the old token answers into nothing.
    const late = run(
      pending('1', 'alice'),
      setToken('bob'),
      fulfilled('1', [tool('a')]),
    );
    expect(late.tools).toEqual([]);
    expect(late.loaded).toBe(false);
    const failed = run(pending('1', 'alice'), setToken('bob'), rejected('1'));
    expect(failed.loaded).toBe(false);
    // The new account's own load applies as usual.
    expect(
      run(
        pending('1', 'alice'),
        setToken('bob'),
        pending('2', 'bob'),
        fulfilled('1', [tool('a')]),
        fulfilled('2', [tool('b')]),
      ).tools,
    ).toEqual([tool('b')]);
  });

  // Sign-in sets the token it already has; a load out then still answers.
  it('keeps the list when the same token is set again', () => {
    const state = run(
      pending('1', 'alice'),
      fulfilled('1', [tool('a')]),
      pending('2', 'alice'),
      setToken('alice'),
      fulfilled('2', [tool('b')]),
    );
    expect(state.tools).toEqual([tool('b')]);
    expect(state.loaded).toBe(true);
  });

  // A session renewal hands the same user a new token every few minutes.
  it('keeps the list when a new token names the same user', () => {
    const jwt = (sub: string, exp: number) =>
      `h.${btoa(JSON.stringify({ sub, exp }))}.s`;
    const renewed = run(
      pending('1', jwt('alice', 1)),
      fulfilled('1', [tool('a')]),
      setToken(jwt('alice', 2)),
    );
    expect(renewed.tools).toEqual([tool('a')]);
    expect(renewed.loaded).toBe(true);
    expect(
      run(
        pending('1', jwt('alice', 1)),
        fulfilled('1', [tool('a')]),
        setToken(jwt('bob', 2)),
      ).tools,
    ).toEqual([]);
  });

  it('reads as empty in a store without the slice', () => {
    expect(selectChatTools({})).toEqual([]);
    expect(selectChatToolsLoaded({})).toBe(false);
    expect(selectChatToolsLoading({})).toBe(false);
  });
});
