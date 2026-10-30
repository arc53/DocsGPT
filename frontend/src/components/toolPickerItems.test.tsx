import { renderToStaticMarkup } from 'react-dom/server';

import type { Connection, ConnectorDefinition } from '../connectors/types';
import { deviceOnlineMap, isDeviceOnline } from '../utils/deviceUtils';
import { toolPickerItems } from './toolPickerItems';

vi.mock('./ToolIcon', () => ({ default: () => null }));
vi.mock('../connectors/ConnectorIcon', () => ({
  default: ({ icon }: { icon: string }) => <i data-icon={icon} />,
}));

const t = ((key: string, opts?: Record<string, unknown>) => {
  const { interpolation: _i, ...rest } = opts ?? {};
  void _i;
  return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
}) as never;

const connections = [
  {
    id: 'c-tg',
    connector_key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
    status: 'connected',
    auth_kind: 'api_key',
    account_label: '…p43M',
  },
  {
    id: 'c-lin',
    connector_key: 'mcp:linear',
    name: 'Linear',
    icon: 'linear',
    status: 'reconnect_needed',
    account_label: 'ops@example.com',
    account_name: 'Ops',
  },
] as Connection[];
const catalog = [
  {
    key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
    description: 'Send messages to a chat.',
    publisher: 'built_in',
    tool_templates: ['telegram'],
  },
] as ConnectorDefinition[];

const build = (
  tools: Record<string, unknown>[],
  extra: Partial<Parameters<typeof toolPickerItems>[1]> = {},
) =>
  toolPickerItems(
    tools.map((tool) => ({ name: 'memory', ...tool }) as never),
    { t, connections, catalog, ...extra },
  );

const text = (node: React.ReactNode) =>
  renderToStaticMarkup(<>{node}</>).replace(/<[^>]+>/g, '|');

describe('toolPickerItems', () => {
  it('groups rows like the Tools page, keyed by group, the order kept', () => {
    const items = build([
      { id: 'api', name: 'api_tool', displayName: 'My API' },
      {
        id: 'tg',
        name: 'telegram',
        displayName: 'Telegram',
        connection_id: 'c-tg',
      },
      { id: 'mem', displayName: 'Memory' },
      { id: 'web', name: 'read_webpage', displayName: 'Reader', default: true },
    ]);
    expect(items.map((item) => [item.id, item.group])).toEqual([
      ['web', 'included'],
      ['mem', 'added'],
      ['tg', 'service:Telegram'],
      ['api', 'custom'],
    ]);
    expect(items[0].groupHeading).toBe('settings.tools.groupIncluded');
    expect(items[1].groupHeading).toBe('settings.tools.groupAdded');
    expect(items[3].groupHeading).toBe('agents.form.toolsPopup.groupCustom');
    // A service heading is its icon and name.
    const heading = renderToStaticMarkup(<>{items[2].groupHeading}</>);
    expect(heading).toContain('data-icon="tool_telegram"');
    expect(heading).toContain('Telegram');
  });

  it("puts the account on a connected tool's line, not a prefix in its name", () => {
    const [row] = build([
      {
        id: 'tg',
        name: 'telegram',
        displayName: 'Telegram · …p43M',
        description: 'Send messages',
        connection_id: 'c-tg',
      },
    ]);
    expect(row.label).toBe('Telegram');
    expect(row.description).toBe(
      'settings.connectors.detail.keyEnding:{"hint":"…p43M"}',
    );
  });

  it('gives any other tool its catalog text as the line', () => {
    const [row] = build([
      { id: 'mem', displayName: 'Memory', description: 'Remembers things' },
    ]);
    expect(row.description).toBe('Remembers things');
    expect(row.descriptionNode).toBeUndefined();
  });

  it('joins a line suffix to the row line, or stands alone without one', () => {
    const [withLine, bare] = build(
      [
        { id: 'mem', displayName: 'Memory', description: 'Remembers things' },
        { id: 'raw', displayName: 'Raw' },
      ],
      { lineSuffix: () => 'Added by Lena' },
    );
    expect(withLine.description).toBe('Remembers things · Added by Lena');
    expect(bare.description).toBe('Added by Lena');
  });

  it("names a teammate's tool by who shared it before anything else", () => {
    const [row] = build([
      {
        id: 'mem',
        displayName: 'Memory',
        description: 'Remembers things',
        access: 'viewer',
        shared_via: 'Ops',
      },
    ]);
    expect(row.description).toBe('settings.tools.sharedBy:{"team":"Ops"}');
  });

  it('stacks the Reconnect badge above the account line', () => {
    const [row] = build([
      {
        id: 'lin',
        name: 'mcp_tool',
        displayName: 'Linear',
        connection_id: 'c-lin',
      },
    ]);
    expect(row.description).toBeUndefined();
    expect(text(row.descriptionNode)).toMatch(
      /settings\.connectors\.status\.reconnect.*Ops/,
    );
    const html = renderToStaticMarkup(<>{row.descriptionNode}</>);
    expect(html).toContain('data-variant="warning"');
  });

  it('marks a remote device online or offline once the status is known', () => {
    const device = {
      id: 'dev',
      name: 'remote_device',
      displayName: 'Laptop',
      description: 'Spreadsheet clean-up',
      config: { device_id: 'd1' },
    };
    const [unknown] = build([device]);
    expect(unknown.descriptionNode).toBeUndefined();
    expect(unknown.description).toBe('Spreadsheet clean-up');

    const [online] = build([device], {
      deviceOnline: new Map([['d1', true]]),
    });
    expect(text(online.descriptionNode)).toMatch(
      /settings\.devices\.online.*Spreadsheet clean-up/,
    );
    const [offline] = build([device], { deviceOnline: new Map() });
    const html = renderToStaticMarkup(<>{offline.descriptionNode}</>);
    expect(html).toContain('settings.devices.offline');
    expect(html).toContain('data-variant="neutral"');
  });

  it('takes a line from lineFor first', () => {
    const [row] = build(
      [{ id: 'x', display_name: 'Owner Jira', name: 'jira' }],
      {
        lineFor: () => 'Added by someone else.',
      },
    );
    expect(row.label).toBe('Owner Jira');
    expect(row.description).toBe('Added by someone else.');
  });
});

describe('isDeviceOnline', () => {
  it('counts a device seen in the last 30 seconds as online', () => {
    const now = Date.parse('2026-10-30T12:00:00Z');
    expect(isDeviceOnline({ last_seen_at: '2026-10-30T11:59:45Z' }, now)).toBe(
      true,
    );
    expect(isDeviceOnline({ last_seen_at: '2026-10-30T11:59:00Z' }, now)).toBe(
      false,
    );
    expect(isDeviceOnline({ last_seen_at: null }, now)).toBe(false);
    expect(isDeviceOnline(null, now)).toBe(false);
    expect(
      deviceOnlineMap(
        [
          { id: 'a', last_seen_at: '2026-10-30T11:59:59Z' },
          { id: 'b', last_seen_at: 'nonsense' },
        ],
        now,
      ),
    ).toEqual(
      new Map([
        ['a', true],
        ['b', false],
      ]),
    );
  });
});
