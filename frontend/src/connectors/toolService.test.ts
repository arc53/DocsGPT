import { toolServiceOf } from './toolService';
import type { Connection, ConnectorDefinition } from './types';

const connection = (overrides: Partial<Connection>): Connection =>
  ({
    id: 'conn-1',
    connector_key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
    account_label: '…abcd',
    status: 'connected',
    ...overrides,
  }) as Connection;

const connector = (
  overrides: Partial<ConnectorDefinition>,
): ConnectorDefinition =>
  ({
    key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
    publisher: 'built_in',
    tool_templates: ['telegram'],
    mcp_url: null,
    credential_policy: 'choose',
    ...overrides,
  }) as ConnectorDefinition;

const CATALOG = [
  connector({}),
  connector({
    key: 'linear',
    name: 'Linear',
    icon: 'linear',
    publisher: 'preset',
    tool_templates: ['mcp_tool'],
    mcp_url: 'https://mcp.linear.app/mcp',
  }),
  connector({
    key: 'custom_mcp',
    name: 'MCP server',
    icon: 'tool_mcp_tool',
    publisher: 'custom',
    tool_templates: ['mcp_tool'],
  }),
  connector({
    key: 'custom_openapi',
    name: 'OpenAPI / REST',
    icon: 'tool_api_tool',
    publisher: 'custom',
    tool_templates: ['api_tool'],
  }),
];

describe('toolServiceOf', () => {
  it('is undefined for a tool with no connection', () => {
    expect(
      toolServiceOf(
        { name: 'api_tool', displayName: 'My API', connection_id: null },
        [],
        CATALOG,
      ),
    ).toBeUndefined();
  });

  it("uses the caller's own connection when it is loaded", () => {
    const own = connection({});
    expect(
      toolServiceOf(
        { name: 'telegram', displayName: 'Telegram', connection_id: 'conn-1' },
        [own],
        CATALOG,
      ),
    ).toEqual({
      name: 'Telegram',
      icon: 'tool_telegram',
      connection: own,
      connector: CATALOG[0],
    });
  });

  it("names a teammate's built-in service tool after its connector", () => {
    const service = toolServiceOf(
      {
        name: 'telegram',
        displayName: 'Telegram · Alerts bot',
        connection_id: 'owner-conn',
      },
      [],
      CATALOG,
    );
    expect(service).toEqual({
      name: 'Telegram',
      icon: 'tool_telegram',
      connector: CATALOG[0],
    });
  });

  it("matches a teammate's MCP preset by its server", () => {
    const service = toolServiceOf(
      {
        name: 'mcp_tool',
        displayName: 'Linear',
        connection_id: 'owner-conn',
        config: { server_url: 'https://mcp.linear.app/sse' },
      },
      [],
      CATALOG,
    );
    expect(service?.name).toBe('Linear');
    expect(service?.icon).toBe('linear');
  });

  it("groups a teammate's custom server under its own name, without an account", () => {
    const service = toolServiceOf(
      {
        name: 'mcp_tool',
        displayName: 'Carrier Rates · ops@x',
        connection_id: 'owner-conn',
        config: { server_url: 'https://rates.example.com/mcp' },
      },
      [],
      CATALOG,
    );
    expect(service).toEqual({ name: 'Carrier Rates', icon: null });
  });
});
