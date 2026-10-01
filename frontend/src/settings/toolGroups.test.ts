import type { Connection, ConnectorDefinition } from '../connectors/types';
import { groupTools, isCustomTool } from './toolGroups';

const tool = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  name: 'memory',
  displayName: id,
  connection_id: null as string | null,
  ...overrides,
});

const connections = [
  {
    id: 'c-tg',
    connector_key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
  },
  { id: 'c-lin', connector_key: 'mcp:linear', name: 'Linear', icon: 'linear' },
] as Connection[];
const catalog = [] as ConnectorDefinition[];

describe('groupTools', () => {
  it('groups built in first, then one group per service, then custom', () => {
    const groups = groupTools(
      [
        tool('api', { name: 'api_tool' }),
        tool('tg', { name: 'telegram', connection_id: 'c-tg' }),
        tool('mem'),
        tool('lin', { name: 'mcp_tool', connection_id: 'c-lin' }),
        tool('mcp', { name: 'mcp_tool' }),
        tool('tg2', { name: 'telegram', connection_id: 'c-tg' }),
        tool('web', { name: 'read_webpage' }),
      ],
      connections,
      catalog,
    );
    expect(groups.map((g) => [g.kind, g.service?.name])).toEqual([
      ['builtIn', undefined],
      ['service', 'Telegram'],
      ['service', 'Linear'],
      ['custom', undefined],
    ]);
    expect(groups.map((g) => g.tools.map((t) => t.id))).toEqual([
      ['mem', 'web'],
      ['tg', 'tg2'],
      ['lin'],
      ['api', 'mcp'],
    ]);
    expect(groups[1].service?.icon).toBe('tool_telegram');
  });

  it('leaves out empty groups', () => {
    const groups = groupTools([tool('mem')], connections, catalog);
    expect(groups.map((g) => g.kind)).toEqual(['builtIn']);
  });

  it('counts only an API or MCP tool with no connection as custom', () => {
    expect(isCustomTool(tool('a', { name: 'api_tool' }))).toBe(true);
    expect(isCustomTool(tool('m', { name: 'mcp_tool' }))).toBe(true);
    expect(
      isCustomTool(tool('l', { name: 'mcp_tool', connection_id: 'c-lin' })),
    ).toBe(false);
    expect(isCustomTool(tool('mem'))).toBe(false);
  });
});
