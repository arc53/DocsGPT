import type { Connection, ConnectorDefinition } from '../connectors/types';
import {
  groupTools,
  isCustomTool,
  isIncludedTool,
  toolGroupLabel,
} from './toolGroups';

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
  it('groups included, added, one group per service, then custom', () => {
    const groups = groupTools(
      [
        tool('api', { name: 'api_tool' }),
        tool('tg', { name: 'telegram', connection_id: 'c-tg' }),
        tool('mem'),
        tool('lin', { name: 'mcp_tool', connection_id: 'c-lin' }),
        tool('mcp', { name: 'mcp_tool' }),
        tool('tg2', { name: 'telegram', connection_id: 'c-tg' }),
        tool('web', { name: 'read_webpage', default: true }),
        tool('code', { name: 'code_executor', builtin: true }),
        tool('sched', { name: 'scheduler', builtin: true, default: true }),
      ],
      connections,
      catalog,
    );
    expect(groups.map((g) => [g.kind, g.service?.name])).toEqual([
      ['included', undefined],
      ['added', undefined],
      ['service', 'Telegram'],
      ['service', 'Linear'],
      ['custom', undefined],
    ]);
    expect(groups.map((g) => g.tools.map((t) => t.id))).toEqual([
      ['web', 'code', 'sched'],
      ['mem'],
      ['tg', 'tg2'],
      ['lin'],
      ['api', 'mcp'],
    ]);
    expect(groups[2].service?.icon).toBe('tool_telegram');
  });

  // The two Memory rows: the one that comes with DocsGPT and the one the
  // user added from the catalog land in different groups.
  it('tells the default copy of a tool from an added one', () => {
    const groups = groupTools(
      [tool('mine'), tool('default', { default: true })],
      connections,
      catalog,
    );
    expect(groups.map((g) => [g.key, g.tools.map((t) => t.id)])).toEqual([
      ['included', ['default']],
      ['added', ['mine']],
    ]);
  });

  it('leaves out empty groups', () => {
    const groups = groupTools([tool('mem')], connections, catalog);
    expect(groups.map((g) => g.kind)).toEqual(['added']);
  });

  it('counts only an API or MCP tool with no connection as custom', () => {
    expect(isCustomTool(tool('a', { name: 'api_tool' }))).toBe(true);
    expect(isCustomTool(tool('m', { name: 'mcp_tool' }))).toBe(true);
    expect(
      isCustomTool(tool('l', { name: 'mcp_tool', connection_id: 'c-lin' })),
    ).toBe(false);
    expect(isCustomTool(tool('mem'))).toBe(false);
  });

  it('counts a default or builtin tool as included', () => {
    expect(isIncludedTool(tool('d', { default: true }))).toBe(true);
    expect(isIncludedTool(tool('b', { builtin: true }))).toBe(true);
    expect(isIncludedTool(tool('mem'))).toBe(false);
  });
});

describe('toolGroupLabel', () => {
  const t = ((key: string) => key) as never;

  it('names each kind, and a service by its own name', () => {
    const groups = groupTools(
      [
        tool('d', { default: true }),
        tool('mem'),
        tool('tg', { name: 'telegram', connection_id: 'c-tg' }),
        tool('api', { name: 'api_tool' }),
      ],
      connections,
      catalog,
    );
    expect(groups.map((group) => toolGroupLabel(t, group))).toEqual([
      'settings.tools.groupIncluded',
      'settings.tools.groupAdded',
      'Telegram',
      'agents.form.toolsPopup.groupCustom',
    ]);
  });
});
