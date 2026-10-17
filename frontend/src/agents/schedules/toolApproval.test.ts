import {
  approvalGatedTools,
  buildToolAllowlist,
  initialApprovedIds,
  toolNeedsApproval,
} from './toolApproval';

describe('toolNeedsApproval', () => {
  it('is false when no active action needs approval', () => {
    expect(
      toolNeedsApproval({
        id: 't1',
        name: 'read_webpage',
        actions: [{ name: 'read', active: true, require_approval: false }],
      }),
    ).toBe(false);
  });

  it('is true when an active action needs approval', () => {
    expect(
      toolNeedsApproval({
        id: 't1',
        name: 'mcp_tool',
        actions: [
          { name: 'list', active: true },
          { name: 'delete', active: true, require_approval: true },
        ],
      }),
    ).toBe(true);
  });

  it('ignores inactive actions, which never run', () => {
    expect(
      toolNeedsApproval({
        id: 't1',
        name: 'mcp_tool',
        actions: [{ name: 'delete', active: false, require_approval: true }],
      }),
    ).toBe(false);
  });

  it('reads an API tool’s actions from its config', () => {
    expect(
      toolNeedsApproval({
        id: 't1',
        name: 'api_tool',
        actions: [],
        config: {
          actions: {
            get_order: { active: true },
            refund: { active: true, require_approval: true },
          },
        },
      }),
    ).toBe(true);
  });

  it('follows the code executor’s own require_approval setting', () => {
    expect(
      toolNeedsApproval({
        id: 't1',
        name: 'code_executor',
        actions: [{ name: 'run_code', active: true }],
        config: { require_approval: true },
      }),
    ).toBe(true);
  });

  it('always treats a remote device as needing approval', () => {
    expect(
      toolNeedsApproval({ id: 't1', name: 'remote_device', actions: [] }),
    ).toBe(true);
  });
});

describe('approvalGatedTools', () => {
  const agentTools = [
    { id: 'safe', name: 'read_webpage', display_name: 'Read webpage' },
    { id: 'gated', name: 'mcp_tool', display_name: 'MCP' },
    { id: 'unknown', name: 'api_tool', display_name: 'Owner API' },
  ];
  const userTools = [
    { id: 'safe', name: 'read_webpage', actions: [{ name: 'read' }] },
    {
      id: 'gated',
      name: 'mcp_tool',
      customName: 'GitHub',
      actions: [{ name: 'create_issue', require_approval: true }],
    },
  ];

  it('lists tools that need approval and tools the caller cannot inspect', () => {
    expect(approvalGatedTools(agentTools, userTools)).toEqual([
      { id: 'gated', name: 'GitHub' },
      { id: 'unknown', name: 'Owner API' },
    ]);
  });
});

describe('initialApprovedIds', () => {
  it('ticks nothing for a new schedule', () => {
    expect(initialApprovedIds(['a', 'b'], undefined)).toEqual([]);
  });

  it('ticks the gated tools a saved schedule already allows', () => {
    expect(initialApprovedIds(['a', 'b'], ['b', 'x'])).toEqual(['b']);
  });
});

describe('buildToolAllowlist', () => {
  it('sends only the ticked gated tools for a new schedule', () => {
    expect(buildToolAllowlist(['a', 'b'], ['b'], undefined)).toEqual(['b']);
  });

  it('keeps saved entries the form does not show', () => {
    expect(buildToolAllowlist(['a', 'b'], ['a'], ['b', 'x'])).toEqual([
      'x',
      'a',
    ]);
  });

  it('never sends a tool that is not ticked', () => {
    expect(buildToolAllowlist(['a'], [], undefined)).toEqual([]);
  });
});
