import { describe, expect, it } from 'vitest';

import {
  canAddToolToOwn,
  isAgentPickerToolVisible,
  isChatPickerToolVisible,
  isChatToolVisible,
  isClassicAgentToolVisible,
  isServerAttachedTool,
  isSharedOAuthMcp,
  toolInChat,
} from './toolUtils';

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

// The classic agent picker hides ``workflow_only`` builtins (e.g.
// read_document); the workflow-node picker keeps them (no filter there).
describe('isClassicAgentToolVisible', () => {
  it('drops workflow-only builtins (e.g. read_document)', () => {
    expect(isClassicAgentToolVisible({ workflow_only: true })).toBe(false);
  });

  it('keeps non-workflow-only tools', () => {
    expect(isClassicAgentToolVisible({ workflow_only: false })).toBe(true);
    expect(isClassicAgentToolVisible({})).toBe(true);
  });
});

// The "In my chats" switch: the owner's value is ``status``; a grantee's is
// their own ``in_chat`` preference, which the server sends for everyone.
describe('toolInChat', () => {
  it('prefers in_chat over status', () => {
    expect(toolInChat({ status: true, in_chat: false })).toBe(false);
    expect(toolInChat({ status: false, in_chat: true })).toBe(true);
  });

  it('falls back to status when in_chat is absent', () => {
    expect(toolInChat({ status: true })).toBe(true);
    expect(toolInChat({ status: false })).toBe(false);
  });
});

describe('canAddToolToOwn', () => {
  it("allows the caller's own tools", () => {
    expect(canAddToolToOwn({})).toBe(true);
    expect(canAddToolToOwn({ access: 'owner', allowed_actions: [] })).toBe(
      true,
    );
  });

  it('follows use_in_own for a shared tool', () => {
    expect(
      canAddToolToOwn({ access: 'viewer', allowed_actions: ['use'] }),
    ).toBe(false);
    expect(
      canAddToolToOwn({
        access: 'viewer',
        allowed_actions: ['use', 'use_in_own'],
      }),
    ).toBe(true);
  });

  it('falls back to the role default for a legacy shared row', () => {
    // Viewers and editors may add a shared tool to their own agents by default.
    expect(canAddToolToOwn({ ownership: 'team', team_access: 'editor' })).toBe(
      true,
    );
  });
});

describe('isSharedOAuthMcp', () => {
  const oauth = { name: 'mcp_tool', config: { auth_type: 'oauth' } };

  it('is true only for an OAuth MCP server shared with the caller', () => {
    expect(isSharedOAuthMcp({ ...oauth, access: 'editor' })).toBe(true);
    expect(isSharedOAuthMcp({ ...oauth, access: 'owner' })).toBe(false);
    expect(isSharedOAuthMcp(oauth)).toBe(false);
    expect(
      isSharedOAuthMcp({
        name: 'mcp_tool',
        access: 'editor',
        config: { auth_type: 'bearer' },
      }),
    ).toBe(false);
    expect(
      isSharedOAuthMcp({ ...oauth, name: 'api_tool', access: 'editor' }),
    ).toBe(false);
  });
});

describe('isChatPickerToolVisible', () => {
  it('hides shared tools the caller may not add to their own chats', () => {
    expect(
      isChatPickerToolVisible({ access: 'viewer', allowed_actions: ['use'] }),
    ).toBe(false);
  });

  it("keeps shared tools with use_in_own and the caller's own tools", () => {
    expect(
      isChatPickerToolVisible({
        access: 'editor',
        allowed_actions: ['use', 'use_in_own', 'edit'],
      }),
    ).toBe(true);
    expect(isChatPickerToolVisible({})).toBe(true);
  });

  it('still drops pure builtins', () => {
    expect(isChatPickerToolVisible({ builtin: true })).toBe(false);
  });
});

describe('isAgentPickerToolVisible', () => {
  it('keeps own tools and shared tools usable in own agents', () => {
    expect(isAgentPickerToolVisible({})).toBe(true);
    expect(
      isAgentPickerToolVisible({
        access: 'viewer',
        allowed_actions: ['use', 'use_in_own'],
      }),
    ).toBe(true);
  });

  it('hides shared tools without use_in_own and workflow-only builtins', () => {
    expect(
      isAgentPickerToolVisible({ access: 'viewer', allowed_actions: ['use'] }),
    ).toBe(false);
    expect(isAgentPickerToolVisible({ workflow_only: true })).toBe(false);
  });
});

describe('server-attached tools (check_job)', () => {
  const checkJob = { name: 'check_job', default: true, status: true };

  it('are never offered as a choice: composer, Settings > Tools, agent picker', () => {
    expect(isServerAttachedTool(checkJob)).toBe(true);
    expect(isChatToolVisible(checkJob)).toBe(false);
    expect(isChatPickerToolVisible(checkJob)).toBe(false);
    expect(isClassicAgentToolVisible(checkJob)).toBe(false);
    expect(isAgentPickerToolVisible(checkJob)).toBe(false);
  });

  it('leave monitor and the other defaults where they were', () => {
    const monitor = { name: 'monitor', default: true, builtin: true };
    expect(isServerAttachedTool(monitor)).toBe(false);
    expect(isChatPickerToolVisible(monitor)).toBe(true);
    expect(isAgentPickerToolVisible(monitor)).toBe(true);
    expect(isChatPickerToolVisible({ name: 'scheduler', default: true })).toBe(
      true,
    );
  });
});
