import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import type { ToolCallsType } from '../conversation/types';
import {
  getToolChipLabel,
  readableAction,
  toolCallTitle,
} from './streamingStatusUtils';

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

  it('names a call that never ran without claiming it did', () => {
    const memory = call({
      tool_name: 'memory',
      action_name: 'memory_create',
      arguments: { path: '/notes.md' },
    });
    expect(getToolChipLabel(memory, t)).toBe(
      'conversation.toolChip.memorySave|/notes.md',
    );
    for (const not_run of ['moved_on', 'expired', undefined] as const) {
      expect(
        getToolChipLabel({ ...memory, status: 'denied', not_run }, t),
      ).toBe('conversation.toolApproval.title|Memory,Create');
    }
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

  it('falls back to the tool and its action for unknown tools', () => {
    expect(
      getToolChipLabel(
        call({ tool_name: 'mcp_tool', action_name: 'some_dynamic_action' }),
        t,
      ),
    ).toBe('conversation.toolChip.usedToolAction|Mcp Tool,some dynamic action');
    expect(
      getToolChipLabel(
        call({
          tool_name: 'mcp_tool',
          action_name: 'some_dynamic_action',
          status: 'pending',
        }),
        t,
      ),
    ).toBe(
      'conversation.streamingStatus.usedToolAction|Mcp Tool,some dynamic action',
    );
  });

  it('keeps the bare tool name when the action only repeats it', () => {
    expect(
      getToolChipLabel(
        call({ tool_name: 'read_document', action_name: 'read_document' }),
        t,
      ),
    ).toBe('conversation.toolChip.usingTool|Read Document');
    expect(
      getToolChipLabel(call({ tool_name: 'think', action_name: '' }), t),
    ).toBe('conversation.toolChip.usingTool|Think');
  });
  it('names a connection-backed call after its service', () => {
    const notion = { tool_name: 'mcp_tool', connector_name: 'Notion' };
    expect(
      getToolChipLabel(
        call({ ...notion, action_name: 'notion-search', access: 'read' }),
        t,
      ),
    ).toBe('conversation.toolChip.searchedConnector|Notion');
    expect(
      getToolChipLabel(
        call({
          ...notion,
          action_name: 'notion-fetch',
          access: 'read',
          status: 'pending',
        }),
        t,
      ),
    ).toBe('conversation.streamingStatus.usingConnector|Notion');
    expect(
      getToolChipLabel(
        call({ ...notion, action_name: 'notion-fetch', access: 'read' }),
        t,
      ),
    ).toBe('conversation.toolChip.readConnector|Notion');
  });

  it('names the action of a write without the service prefix', () => {
    expect(
      getToolChipLabel(
        call({
          tool_name: 'mcp_tool',
          connector_name: 'Linear',
          action_name: 'linear_create_issue',
          access: 'write',
        }),
        t,
      ),
    ).toBe('conversation.toolChip.usedConnector|Linear,create issue');
    expect(
      getToolChipLabel(
        call({
          tool_name: 'telegram',
          connector_name: 'Telegram',
          action_name: 'send_message',
          access: 'write',
        }),
        t,
      ),
    ).toBe('conversation.toolChip.usedConnector|Telegram,send message');
  });

  it('keeps built-in labels for web search even with a connector name', () => {
    expect(
      getToolChipLabel(
        call({ connector_name: 'Brave', arguments: { query: 'docsgpt' } }),
        t,
      ),
    ).toBe('conversation.toolChip.searchingWeb|docsgpt');
  });
});

describe('readableAction', () => {
  it('drops the service prefix and keeps a bare verb', () => {
    expect(readableAction('linear_create_issue', 'Linear')).toBe(
      'create issue',
    );
    expect(readableAction('notion-create-pages', 'Notion')).toBe(
      'create pages',
    );
    expect(readableAction('create_issue', 'GitHub')).toBe('create issue');
    expect(readableAction('search', 'Notion')).toBe('search');
  });

  it('reads without a service name', () => {
    expect(readableAction('run_command')).toBe('run command');
  });
});

describe('toolCallTitle', () => {
  it('names the connector and its action in sentence case', () => {
    expect(
      toolCallTitle(
        call({
          tool_name: 'github',
          action_name: 'create_issue',
          connector_key: 'github',
          connector_name: 'GitHub',
        }),
        t,
      ),
    ).toBe('conversation.toolApproval.title|GitHub,Create issue');
  });

  it('shows a dash-named MCP action', () => {
    expect(
      toolCallTitle(
        call({
          tool_name: 'mcp_tool',
          action_name: 'notion-create-pages',
          connector_key: 'mcp:notion',
          connector_name: 'Notion',
        }),
        t,
      ),
    ).toBe('conversation.toolApproval.title|Notion,Create pages');
  });

  it('falls back to the tool name without a connector', () => {
    expect(
      toolCallTitle(
        call({ tool_name: 'remote_device', action_name: 'run_command' }),
        t,
      ),
    ).toBe('conversation.toolApproval.title|Remote Device,Run command');
  });
});

describe('getToolChipLabel for the attachments tool', () => {
  const files = (overrides: Partial<ToolCallsType>) =>
    call({ tool_name: 'attachments', ...overrides });

  it('names a search by its query', () => {
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_search',
          arguments: { query: 'enzymes', refs: ['F1', 'F2'] },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsSearch|enzymes');
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_search',
          arguments: { query: 'enzymes' },
          status: 'pending',
        }),
        t,
      ),
    ).toBe('conversation.streamingStatus.attachmentsSearch|enzymes');
    expect(
      getToolChipLabel(files({ action_name: 'attachments_search' }), t),
    ).toBe('conversation.toolChip.attachmentsSearchGeneric');
  });

  it('names a read by its file and the pages or rows it asked for', () => {
    expect(
      getToolChipLabel(
        files({ action_name: 'attachments_read', arguments: { ref: 'f3' } }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsRead|F3');
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_read',
          arguments: { ref: 'F3', pages: '2-4' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsReadPages|F3,2–4');
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_read',
          arguments: { ref: 'F3', pages: '5' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsReadPage|F3,5');
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_read',
          arguments: { ref: 'F2', rows: '100-200' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsReadRows|F2,100–200');
    expect(
      getToolChipLabel(files({ action_name: 'attachments_read' }), t),
    ).toBe('conversation.toolChip.attachmentsReadGeneric');
  });

  it('says an image was viewed when the read showed one', () => {
    expect(
      getToolChipLabel(
        files({
          action_name: 'attachments_read',
          arguments: { ref: 'F7' },
          result:
            'Image F7 photo.png is attached below in a follow-up message.' as unknown as Record<
              string,
              unknown
            >,
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsImage|F7');
    // A# refs are image artifacts of the conversation.
    expect(
      getToolChipLabel(
        files({ action_name: 'attachments_read', arguments: { ref: 'A2' } }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsImage|A2');
  });

  it('names a listing', () => {
    expect(
      getToolChipLabel(files({ action_name: 'attachments_list' }), t),
    ).toBe('conversation.toolChip.attachmentsList');
  });

  it('accepts the docsgpt_ prefix the actions take beside a client tool', () => {
    expect(
      getToolChipLabel(
        files({
          action_name: 'docsgpt_attachments_search',
          arguments: { query: 'cells' },
        }),
        t,
      ),
    ).toBe('conversation.toolChip.attachmentsSearch|cells');
    expect(
      getToolChipLabel(files({ action_name: 'docsgpt_attachments_list' }), t),
    ).toBe('conversation.toolChip.attachmentsList');
  });

  it('leaves another tool with a look-alike action alone', () => {
    expect(
      getToolChipLabel(
        call({ tool_name: 'mcp_tool', action_name: 'attachments_list' }),
        t,
      ),
    ).toBe('conversation.toolChip.usedToolAction|Mcp Tool,attachments list');
  });
});

describe('getToolChipLabel for built-in tools', () => {
  const label = (overrides: Partial<ToolCallsType>) =>
    getToolChipLabel(call(overrides), t);
  const chip = 'conversation.toolChip.';

  it('names wiki reads by page', () => {
    expect(
      label({
        tool_name: 'wiki',
        action_name: 'wiki_view',
        arguments: { path: '/' },
      }),
    ).toBe(`${chip}wikiList`);
    expect(label({ tool_name: 'wiki', action_name: 'wiki_view' })).toBe(
      `${chip}wikiList`,
    );
    expect(
      label({
        tool_name: 'wiki',
        action_name: 'wiki_view',
        arguments: { path: '/sales/pricing.md' },
      }),
    ).toBe(`${chip}wikiRead|/sales/pricing.md`);
    expect(
      label({
        tool_name: 'wiki',
        action_name: 'wiki_view',
        arguments: { path: '/sales/' },
      }),
    ).toBe(`${chip}wikiList`);
  });

  it('names todo actions by their todo', () => {
    expect(
      label({
        tool_name: 'todo_list',
        action_name: 'todo_create',
        arguments: { title: 'Book the review' },
      }),
    ).toBe(`${chip}todoAdd|Book the review`);
    expect(label({ tool_name: 'todo_list', action_name: 'todo_list' })).toBe(
      `${chip}todoList`,
    );
    expect(
      label({
        tool_name: 'todo_list',
        action_name: 'todo_complete',
        arguments: { todo_id: 5 },
      }),
    ).toBe(`${chip}todoComplete|5`);
    expect(
      label({
        tool_name: 'todo_list',
        action_name: 'todo_update',
        arguments: {},
      }),
    ).toBe(`${chip}usedToolAction|Todo List,update`);
  });

  it('tells the note apart from memory', () => {
    expect(label({ tool_name: 'notes', action_name: 'note_overwrite' })).toBe(
      `${chip}noteUpdate`,
    );
    expect(label({ tool_name: 'notes', action_name: 'note_view' })).toBe(
      `${chip}noteRead`,
    );
    expect(
      label({
        tool_name: 'memory',
        action_name: 'memory_create',
        arguments: { path: '/nordhaven-renewal.md' },
      }),
    ).toBe(`${chip}memorySave|/nordhaven-renewal.md`);
    expect(
      label({
        tool_name: 'memory',
        action_name: 'memory_rename',
        arguments: { old_path: '/a.md', new_path: '/b.md' },
      }),
    ).toBe(`${chip}memoryRename|/a.md`);
  });

  it('names a price check by symbol and currency', () => {
    expect(
      label({
        tool_name: 'cryptoprice',
        action_name: 'cryptoprice_get',
        arguments: { symbol: 'BTC', currency: 'EUR' },
      }),
    ).toBe(`${chip}cryptoPrice|BTC,EUR`);
  });

  it('names messaging and database actions', () => {
    expect(label({ tool_name: 'ntfy', action_name: 'ntfy_send_message' })).toBe(
      `${chip}sentNotification`,
    );
    expect(
      label({ tool_name: 'telegram', action_name: 'telegram_send_image' }),
    ).toBe(`${chip}telegramImage`);
    expect(
      label({ tool_name: 'postgres', action_name: 'postgres_execute_sql' }),
    ).toBe(`${chip}sqlQuery`);
    expect(
      label({ tool_name: 'postgres', action_name: 'postgres_get_schema' }),
    ).toBe(`${chip}dbSchema`);
  });
});
