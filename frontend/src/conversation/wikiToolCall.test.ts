import { describe, expect, it } from 'vitest';

import { ToolCallsType } from './types';
import {
  isWikiWriteCall,
  wikiWriteActionKey,
  wikiWritePath,
} from './wikiToolCall';

const call = (overrides: Partial<ToolCallsType>): ToolCallsType => ({
  tool_name: 'wiki',
  action_name: 'wiki_str_replace',
  call_id: 'c1',
  arguments: {},
  ...overrides,
});

describe('isWikiWriteCall', () => {
  it('flags wiki write actions', () => {
    expect(isWikiWriteCall(call({ action_name: 'wiki_create' }))).toBe(true);
    expect(isWikiWriteCall(call({ action_name: 'wiki_str_replace' }))).toBe(
      true,
    );
    expect(isWikiWriteCall(call({ action_name: 'wiki_insert' }))).toBe(true);
    expect(isWikiWriteCall(call({ action_name: 'wiki_delete' }))).toBe(true);
    expect(isWikiWriteCall(call({ action_name: 'wiki_rename' }))).toBe(true);
  });

  it('does not flag wiki read actions', () => {
    expect(isWikiWriteCall(call({ action_name: 'wiki_view' }))).toBe(false);
  });

  it('does not flag non-wiki tools', () => {
    expect(
      isWikiWriteCall(
        call({ tool_name: 'memory', action_name: 'wiki_create' }),
      ),
    ).toBe(false);
  });
});

describe('wikiWritePath', () => {
  it('reads the path argument for str_replace', () => {
    const tc = call({
      action_name: 'wiki_str_replace',
      arguments: { path: '/policy.md', old_str: 'a', new_str: 'b' },
    });
    expect(wikiWritePath(tc)).toBe('/policy.md');
  });

  it('prefers new_path for a rename', () => {
    const tc = call({
      action_name: 'wiki_rename',
      arguments: { old_path: '/a.md', new_path: '/b.md' },
    });
    expect(wikiWritePath(tc)).toBe('/b.md');
  });

  it('returns null when no path is present in the payload', () => {
    expect(wikiWritePath(call({ arguments: {} }))).toBeNull();
  });
});

describe('wikiWriteActionKey', () => {
  it('strips the wiki_ prefix', () => {
    expect(wikiWriteActionKey('wiki_str_replace')).toBe('str_replace');
    expect(wikiWriteActionKey('wiki_create')).toBe('create');
  });
});
