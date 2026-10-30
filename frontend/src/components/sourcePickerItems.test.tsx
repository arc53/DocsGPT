import { renderToStaticMarkup } from 'react-dom/server';

import type { Connection } from '../connectors/types';
import type { Doc } from '../models/misc';
import { toSourcePickerItems } from './sourcePickerItems';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../connectors/ConnectorIcon', () => ({
  default: ({ icon }: { icon: string }) => <i data-icon={icon} />,
}));

const t = ((key: string, opts?: Record<string, unknown>) => {
  const { interpolation: _i, ...rest } = opts ?? {};
  void _i;
  return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
}) as never;

const labels = { own: 'Yours', team: 'Shared with team' };

const doc = (overrides: Partial<Doc>): Doc => ({
  name: 'doc',
  date: '',
  model: 'm',
  ...overrides,
});

const s3 = {
  id: 'c-s3',
  name: 'Amazon S3',
  icon: 's3',
  status: 'connected',
} as Connection;

const build = (
  docs: Doc[] | null | undefined,
  connections: Connection[] = [],
) => toSourcePickerItems(docs, { t, labels, connections });

/** The row's icon as markup: a lucide class, or the connector logo's key. */
const iconOf = (item: ReturnType<typeof build>[number]) =>
  renderToStaticMarkup(<>{item.icon}</>);

describe('toSourcePickerItems', () => {
  it('returns no items for a missing list', () => {
    expect(build(null)).toEqual([]);
    expect(build(undefined)).toEqual([]);
  });

  it('groups the caller’s own sources even when there are no team ones', () => {
    // The picker drops a lone group's heading (`loneGroupHeading={false}`),
    // but beside Selected the rest still gets its "Yours" heading.
    const items = build([
      doc({ id: 'a', name: 'A' }),
      doc({ id: 'b', name: 'B', ownership: 'user' }),
    ]);
    expect(items.map((item) => [item.id, item.label, item.group])).toEqual([
      ['a', 'A', 'Yours'],
      ['b', 'B', 'Yours'],
    ]);
  });

  it('draws a lucide icon at the tile size in the foreground, as tool rows do', () => {
    const html = iconOf(build([doc({ id: 'a' })])[0]);
    expect(html).toContain('size-5');
    expect(html).toContain('text-foreground');
  });

  it('groups own sources first, then team-shared ones', () => {
    const items = build([
      doc({ id: 't1', name: 'Team one', ownership: 'team' }),
      doc({ id: 'o1', name: 'Own one', ownership: 'user' }),
      doc({ id: 't2', name: 'Team two', ownership: 'team' }),
      doc({ id: 'o2', name: 'Own two' }),
    ]);
    expect(items.map((item) => [item.id, item.group])).toEqual([
      ['o1', 'Yours'],
      ['o2', 'Yours'],
      ['t1', 'Shared with team'],
      ['t2', 'Shared with team'],
    ]);
  });

  // Not the same database icon on every row.
  it.each<[string, Partial<Doc>, string]>([
    [
      'a website',
      { website: { hosts: ['a.io'], pages: 1 }, type: 'website' },
      'lucide-globe',
    ],
    ['a wiki', { type: 'wiki' }, 'lucide-book-open'],
    [
      'a graph upload',
      { type: 'local', config: { kind: 'graphrag' } },
      'lucide-network',
    ],
    ['an upload', { type: 'local' }, 'lucide-file-text'],
    [
      'a provider without a visible connection',
      { type: 'connector:x', provider: 'confluence' },
      'data-icon="confluence"',
    ],
    [
      'a synced source of an unknown provider',
      { type: 'connector:x', provider: 'box' },
      'lucide-cloud',
    ],
  ])('%s gets its own icon', (_, fields, expected) => {
    expect(iconOf(build([doc({ id: 'a', ...fields })])[0])).toContain(expected);
  });

  it("a source from the caller's connection shows the connection's logo", () => {
    const [item] = build([doc({ id: 'a', connectionId: 'c-s3' })], [s3]);
    expect(iconOf(item)).toContain('data-icon="s3"');
  });

  it("the row's line is the card's details", () => {
    const [website, upload] = build([
      doc({
        id: 'w',
        website: { hosts: ['docs.docsgpt.cloud'], pages: 9 },
        syncFrequency: 'weekly',
      }),
      doc({ id: 'u', date: '2026-10-23 13:36', tokens: '224' }),
    ]);
    expect(website.description).toBe(
      'settings.sources.website.pageCount:{"count":9}'
        .replace(/^/, 'docs.docsgpt.cloud · ')
        .concat(' · settings.sources.syncFrequency.weekly'),
    );
    expect(upload.description).toBe(
      '23/10/2026, 13:36 · settings.sources.tokenCount:{"tokens":"224"}',
    );
  });

  it('badges a failed or running ingest and a connection to sign in again', () => {
    const items = build(
      [
        doc({ id: 'f', ingestStatus: 'failed', date: '2026-10-23 13:36' }),
        doc({ id: 'p', ingestStatus: 'processing' }),
        doc({ id: 'r', connectionId: 'c-s3' }),
        doc({ id: 'ok', tokens: '1' }),
      ],
      [{ ...s3, status: 'reconnect_needed' } as Connection],
    );
    const html = items.map((item) =>
      renderToStaticMarkup(<>{item.descriptionNode}</>),
    );
    expect(html[0]).toContain('settings.sources.ingestFailed');
    expect(html[0]).toContain('23/10/2026, 13:36');
    expect(html[1]).toContain('settings.sources.ingestProcessing');
    expect(html[2]).toContain('settings.connectors.status.reconnect');
    // A badged row's line is still searched.
    expect(items[0].keywords).toEqual(['23/10/2026, 13:36']);
    // A healthy row keeps the plain line.
    expect(items[3].descriptionNode).toBeUndefined();
    expect(items[3].description).toContain('tokenCount');
  });

  it('joins a line suffix to the row line, so it stays one line', () => {
    const [item] = toSourcePickerItems(
      [doc({ id: 'u', date: '2026-10-23 13:36' })],
      { t, labels, connections: [], lineSuffix: () => 'Added by Lena' },
    );
    expect(item.description).toBe('23/10/2026, 13:36 · Added by Lena');
  });
});
