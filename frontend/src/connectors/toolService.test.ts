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

  describe("a team tool on each person's own account (no connection)", () => {
    const member = (overrides: Record<string, unknown>) => ({
      name: 'telegram',
      displayName: 'Telegram',
      connection_id: null,
      credential_mode: 'member' as const,
      ...overrides,
    });

    it('goes with its service, found by the service it records', () => {
      expect(
        toolServiceOf(member({ connector_key: 'telegram' }), [], CATALOG),
      ).toEqual({
        name: 'Telegram',
        icon: 'tool_telegram',
        connector: CATALOG[0],
      });
    });

    it('names the same group as a tool on an account for that service', () => {
      const onAccount = toolServiceOf(
        { name: 'telegram', displayName: 'Telegram', connection_id: 'conn-1' },
        [connection({})],
        CATALOG,
      );
      expect(
        toolServiceOf(member({ connector_key: 'telegram' }), [], CATALOG)?.name,
      ).toBe(onAccount?.name);
    });

    it('goes with an MCP preset', () => {
      const service = toolServiceOf(
        member({
          name: 'mcp_tool',
          displayName: 'Linear',
          connector_key: 'linear',
          config: { server_url: 'https://mcp.linear.app/mcp' },
        }),
        [],
        CATALOG,
      );
      expect(service).toEqual({
        name: 'Linear',
        icon: 'linear',
        connector: CATALOG[1],
      });
    });

    it('groups a custom MCP server under its own name', () => {
      const service = toolServiceOf(
        member({
          name: 'mcp_tool',
          displayName: 'Carrier Rates',
          connector_key: 'custom_mcp',
          config: { server_url: 'https://rates.example.com/mcp' },
        }),
        [],
        CATALOG,
      );
      expect(service).toEqual({ name: 'Carrier Rates', icon: null });
    });

    it('is undefined without a recorded service', () => {
      expect(
        toolServiceOf(member({ connector_key: null }), [], CATALOG),
      ).toBeUndefined();
    });
  });
});
