import { describe, expect, it } from 'vitest';

import { isChatToolVisible } from './ToolsPopup';

// Regression for the filter drift introduced when ``scheduler`` was
// dual-registered (both ``default: true`` and ``builtin: true``). The
// chat-popup previously filtered ``!tool.builtin`` and dropped scheduler.
describe('isChatToolVisible', () => {
  it('keeps dual-registered tools (default + builtin, e.g. scheduler)', () => {
    expect(isChatToolVisible({ default: true, builtin: true })).toBe(true);
  });

  it('keeps default-only chat tools (memory, read_webpage before dual-reg)', () => {
    expect(isChatToolVisible({ default: true, builtin: false })).toBe(true);
    expect(isChatToolVisible({ default: true })).toBe(true);
  });

  it('keeps regular user_tools (neither flag set)', () => {
    expect(isChatToolVisible({})).toBe(true);
    expect(isChatToolVisible({ default: false, builtin: false })).toBe(true);
  });

  it('drops pure builtins (agent-only, e.g. a future builtin without default)', () => {
    expect(isChatToolVisible({ builtin: true })).toBe(false);
    expect(isChatToolVisible({ default: false, builtin: true })).toBe(false);
  });
});
