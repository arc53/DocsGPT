import { describe, expect, it } from 'vitest';

import type { UserToolType } from '../settings/types';
import reducer, {
  chatToolsLoadFailed,
  selectChatTools,
  selectChatToolsLoaded,
  setChatToolInChat,
  setChatTools,
} from './chatToolsSlice';

const tool = (id: string): UserToolType =>
  ({ id, name: id, status: false, in_chat: false }) as UserToolType;

describe('chatToolsSlice', () => {
  it('is loaded once a list or a failure arrives', () => {
    expect(
      selectChatToolsLoaded({ chatTools: reducer(undefined, { type: '' }) }),
    ).toBe(false);
    const listed = reducer(undefined, setChatTools([tool('a')]));
    expect(listed.loaded).toBe(true);
    const failed = reducer(listed, chatToolsLoadFailed());
    expect(failed).toEqual({ tools: [tool('a')], loaded: true });
  });

  it("sets the owner's status, and only the grantee's own switch", () => {
    let state = reducer(undefined, setChatTools([tool('a'), tool('b')]));
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

  it('reads as empty in a store without the slice', () => {
    expect(selectChatTools({})).toEqual([]);
    expect(selectChatToolsLoaded({})).toBe(false);
  });
});
