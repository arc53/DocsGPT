import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import type { ToolCallsType } from '../conversation/types';
import { getToolChipLabel } from './streamingStatusUtils';

// Stub that renders "key" or "key|value,value" so assertions can check both
// the selected key and the interpolated values.
const t = ((key: string, opts?: Record<string, unknown>) => {
  const values = opts
    ? Object.entries(opts)
        .filter(([k]) => k !== 'interpolation')
        .map(([, v]) => String(v))
    : [];
  return values.length ? `${key}|${values.join(',')}` : key;
}) as unknown as TFunction;

const call = (overrides: Partial<ToolCallsType>): ToolCallsType => ({
  tool_name: 'brave',
  action_name: 'brave_web_search',
  call_id: 'c1',
  arguments: {},
  status: 'completed',
  ...overrides,
});

describe('getToolChipLabel', () => {
  it('uses present tense while running and past tense once settled', () => {
    const args = { query: 'docsgpt' };
    expect(
      getToolChipLabel(call({ arguments: args, status: 'pending' }), t),
    ).toBe('conversation.streamingStatus.searchingWeb|docsgpt');
    expect(getToolChipLabel(call({ arguments: args }), t)).toBe(
      'conversation.toolChip.searchingWeb|docsgpt',
    );
  });

  it('falls back to the generic search label without a query, per namespace', () => {
    expect(getToolChipLabel(call({ status: 'pending' }), t)).toBe(
      'conversation.streamingStatus.searchingWebGeneric',
    );
    expect(getToolChipLabel(call({}), t)).toBe(
      'conversation.toolChip.searchedWebGeneric',
    );
  });

  it('treats a status-less call as settled, matching the non-shimmer row', () => {
    expect(
      getToolChipLabel(
        call({ arguments: { query: 'docsgpt' }, status: undefined }),
        t,
      ),
    ).toBe('conversation.toolChip.searchingWeb|docsgpt');
    expect(getToolChipLabel(call({ status: undefined }), t)).toBe(
      'conversation.toolChip.searchedWebGeneric',
    );
  });

  it('labels read_webpage with the hostname', () => {
    expect(
      getToolChipLabel(
        call({
          tool_name: 'read_webpage',
          action_name: 'read_webpage',
          arguments: { url: 'https://docs.docsgpt.cloud/quickstart' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.readingPage|docs.docsgpt.cloud');
  });

  it('keeps the raw value when the url does not parse', () => {
    expect(
      getToolChipLabel(
        call({ action_name: 'read_webpage', arguments: { url: 'not a url' } }),
        t,
      ),
    ).toBe('conversation.toolChip.readingPage|not a url');
  });

  it('maps image search, knowledge, memory, code and artifact tools', () => {
    expect(
      getToolChipLabel(
        call({
          action_name: 'ddg_image_search',
          arguments: { query: 'cats' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.searchingImages|cats');
    expect(
      getToolChipLabel(
        call({ tool_name: 'internal_search', action_name: 'search' }),
        t,
      ),
    ).toBe('conversation.toolChip.searchingKnowledge');
    expect(
      getToolChipLabel(
        call({ tool_name: 'memory', action_name: 'memory_view' }),
        t,
      ),
    ).toBe('conversation.toolChip.accessingMemory');
    expect(
      getToolChipLabel(
        call({ tool_name: 'code_executor', action_name: 'run_code' }),
        t,
      ),
    ).toBe('conversation.toolChip.runningCode');
    expect(
      getToolChipLabel(
        call({
          tool_name: 'artifact_generator',
          action_name: 'create_artifact',
        }),
        t,
      ),
    ).toBe('conversation.toolChip.creatingArtifact');
  });

  it('falls back to a formatted tool name for unknown tools', () => {
    expect(
      getToolChipLabel(
        call({ tool_name: 'mcp_tool', action_name: 'some_dynamic_action' }),
        t,
      ),
    ).toBe('conversation.toolChip.usingTool|Mcp Tool');
  });
});
