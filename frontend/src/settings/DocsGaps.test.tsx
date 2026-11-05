import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

import examples from './insights/fixtures/apiExamples.json';
import type { DocsGapRow } from './types';

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'token' } }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      // The interpolation options and the plural count are not shown.
      const shown = Object.entries(opts)
        .filter(([name]) => name !== 'interpolation' && name !== 'count')
        .map(([, value]) => value)
        .join('|');
      return shown ? `${key}(${shown})` : key;
    },
    i18n: { language: 'en' },
  }),
}));

const getDocsGaps = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { getDocsGaps: (...args: unknown[]) => getDocsGaps(...args) },
}));

const downloadCsv = vi.fn();
vi.mock('./docsGapsCsv', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./docsGapsCsv')>()),
  downloadCsv: (...args: unknown[]) => downloadCsv(...args),
}));

import DocsGaps from './DocsGaps';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const row = (overrides: Partial<DocsGapRow> = {}): DocsGapRow => ({
  key: '/install/docker',
  name: 'Installing on Docker',
  source: null,
  expected_gaps: 6.2,
  turns: 31,
  rate: 0.2,
  low: 0.11,
  high: 0.33,
  previous_expected: 4,
  examples: [
    {
      message_id: 'm1',
      conversation_id: 'c1',
      prompt: 'How do I set the port?',
      p: 0.91,
      timestamp: '2026-10-19T10:00:00Z',
    },
  ],
  ...overrides,
});

const respond = (body: object) =>
  getDocsGaps.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        success: true,
        enabled: true,
        previous_labelled: 40,
        ...body,
      }),
  });

describe('DocsGaps', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    localStorage.clear();
    getDocsGaps.mockReset();
    downloadCsv.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    props: Partial<React.ComponentProps<typeof DocsGaps>> = {},
  ) =>
    act(async () =>
      root.render(
        <MemoryRouter>
          <DocsGaps
            agentId="a1"
            agentName="Fintech bot"
            filterOption="last_30_days"
            hasTopics={false}
            {...props}
          />
        </MemoryRouter>,
      ),
    );

  const groupItems = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    );

  it('groups by page first, and offers topic only for an agent with topics', async () => {
    respond({ rows: [row()] });
    await render();
    expect(getDocsGaps).toHaveBeenCalledWith(
      {
        api_key_id: 'a1',
        filter_option: 'last_30_days',
        group_by: 'page',
        limit: 25,
      },
      'token',
    );
    expect(groupItems().map((item) => item.textContent)).toEqual([
      'settings.analytics.gaps.groups.page',
      'settings.analytics.gaps.groups.source',
    ]);
    await render({ hasTopics: true });
    expect(groupItems()).toHaveLength(3);
  });

  it('fetches again by the picked group and remembers it, with a plain heading', async () => {
    respond({ rows: [row()] });
    await render({ hasTopics: true });
    await act(async () => groupItems()[2].click());
    expect(getDocsGaps.mock.calls.at(-1)![0].group_by).toBe('topic');
    expect(localStorage.getItem('DocsGPTDocsGapsGroup')).toBe('topic');
    // No badge in the heading, by any grouping.
    const heading = container.querySelector('h2')!;
    expect(heading.textContent).toBe('settings.analytics.gaps.heading');
    expect(container.querySelector('[data-slot="badge"]')).toBeNull();
  });

  it('falls back to page when a remembered topic grouping does not apply', async () => {
    localStorage.setItem('DocsGPTDocsGapsGroup', 'topic');
    respond({ rows: [] });
    await render({ hasTopics: false });
    expect(getDocsGaps.mock.calls[0][0].group_by).toBe('page');
  });

  it('lists each group with its gaps, share, change and an example, no range', async () => {
    respond({
      rows: [
        row(),
        row({
          key: null,
          name: null,
          expected_gaps: 3,
          previous_expected: 0,
          examples: [],
        }),
      ],
    });
    await render();
    const rows = Array.from(
      container.querySelectorAll<HTMLTableRowElement>('tbody tr'),
    );
    expect(rows).toHaveLength(2);
    const cells = Array.from(rows[0].querySelectorAll('td')).map(
      (cell) => cell.textContent,
    );
    expect(cells[0]).toBe('Installing on Docker');
    expect(cells[1]).toBe('6');
    expect(cells[2]).toBe('settings.analytics.gaps.share(20%|31)');
    expect(cells[3]).toContain('+2');
    expect(cells[3]).toContain('settings.analytics.gaps.change.upLabel(2)');
    expect(cells[4]).toBe('How do I set the port?');
    expect(rows[0].getAttribute('aria-label')).toBe(
      'settings.analytics.gaps.openRow(Installing on Docker)',
    );
    // The number columns are right-aligned and tabular.
    expect(rows[0].querySelectorAll('td')[1].className).toContain(
      'tabular-nums',
    );
    // No page retrieved reads muted; a group that is new says so.
    const second = Array.from(rows[1].querySelectorAll('td'));
    expect(second[0].textContent).toBe('settings.analytics.gaps.noPage');
    expect(second[0].querySelector('.text-muted-foreground')).not.toBeNull();
    expect(second[3].textContent).toBe('settings.analytics.gaps.change.new');
    expect(second[4].textContent).toBe('—');
    // The phone tiles carry the same groups.
    const tiles = container.querySelectorAll('ul.lg\\:hidden > li');
    expect(tiles).toHaveLength(2);
    expect(tiles[0].textContent).toContain(
      'settings.analytics.gaps.gapsCount(6)',
    );
    expect(tiles[0].textContent).not.toContain('–');
  });

  it('colours only the arrows; New, numbers and no change stay plain', async () => {
    respond({
      rows: [
        row(),
        row({ key: '/b', expected_gaps: 2, previous_expected: 4 }),
        row({ key: '/c', expected_gaps: 3, previous_expected: 0 }),
        row({ key: '/d', expected_gaps: 3, previous_expected: 3 }),
      ],
    });
    await render();
    const change = (index: number) =>
      container.querySelectorAll('tbody tr')[index].querySelectorAll('td')[3];
    expect(change(0).querySelector('svg')!.getAttribute('class')).toContain(
      'text-destructive',
    );
    expect(change(1).querySelector('svg')!.getAttribute('class')).toContain(
      'text-success',
    );
    for (const index of [0, 1]) {
      const label = change(index).firstElementChild!;
      expect(label.className).not.toMatch(/text-(destructive|success)/);
    }
    expect(change(2).textContent).toBe('settings.analytics.gaps.change.new');
    expect(change(2).firstElementChild!.className).toContain(
      'text-muted-foreground',
    );
    expect(change(2).innerHTML).not.toContain('text-warning');
    expect(change(3).firstElementChild!.className).toContain(
      'text-muted-foreground',
    );
  });

  it('shows a muted dash while the previous period has no labelled data', async () => {
    respond({ previous_labelled: 0, rows: [row()] });
    await render();
    const cell = container.querySelectorAll('tbody tr td')[3];
    expect(cell.textContent).toBe('—settings.analytics.gaps.change.noEarlier');
    expect(cell.querySelector('[aria-hidden="true"]')!.className).toContain(
      'text-muted-foreground',
    );
    expect(cell.querySelector('.sr-only')!.textContent).toBe(
      'settings.analytics.gaps.change.noEarlier',
    );
    // The phone tile drops the segment; the panel's previous period is a dash.
    const tile = container.querySelector('ul.lg\\:hidden > li')!;
    expect(tile.textContent).not.toContain('noEarlier');
    expect(tile.textContent).not.toContain('upLabel');
    await act(async () =>
      container.querySelector<HTMLTableRowElement>('tbody tr')!.click(),
    );
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(
      Array.from(dialog.querySelectorAll('dd')).map((dd) => dd.textContent)[2],
    ).toBe('—');
  });

  const siteRows = (sources: (string | null)[]) =>
    sources.map((source, index) =>
      row({
        key: `https://docs.example/p${index}`,
        name: `Page ${index} | Example Docs`,
        source,
      }),
    );

  it('strips the shared site tail and titles a row with its shown name', async () => {
    respond({ rows: siteRows(['Core', 'Core']) });
    await render();
    const name = container.querySelector('tbody tr td span')!;
    expect(name.textContent).toBe('Page 0');
    expect(name.getAttribute('title')).toBe('Page 0');
    // One source on an agent: no source line.
    expect(container.querySelector('tbody tr td')!.textContent).toBe('Page 0');
    const tile = container.querySelector('ul.lg\\:hidden > li')!;
    expect(tile.querySelector('[title]')!.getAttribute('title')).toBe('Page 0');
    expect(tile.textContent).not.toContain('Core');
  });

  it("names the source under the page when an agent's rows name several", async () => {
    respond({ rows: siteRows(['Core', 'Old docs']) });
    await render();
    const cell = container.querySelectorAll('tbody tr')[1].querySelector('td')!;
    const lines = cell.querySelectorAll('span');
    expect(lines[0].textContent).toBe('Page 1');
    expect(lines[1].textContent).toBe('Old docs');
    expect(lines[1].className).toContain('text-muted-foreground');
    expect(lines[1].className).toContain('text-xs');
    // The phone tile ends its meta line with the source.
    const meta = container
      .querySelectorAll('ul.lg\\:hidden > li')[1]
      .querySelectorAll('button > div')[1];
    expect(meta.lastElementChild!.textContent).toBe('·Old docs');
  });

  it('always names the source in Settings, and opens a page with its source and URL', async () => {
    respond({ rows: siteRows(['Core', 'Core']) });
    await render({ agentId: undefined });
    const cell = container.querySelector('tbody tr td')!;
    expect(cell.textContent).toBe('Page 0Core');
    await act(async () =>
      container.querySelector<HTMLTableRowElement>('tbody tr')!.click(),
    );
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector('h2')!.textContent).toBe('Page 0');
    const description = dialog.querySelector(
      '[data-slot="sheet-description"]',
    )!;
    expect(description.textContent).toBe('Corehttps://docs.example/p0');
    expect(description.querySelector('.font-mono')!.textContent).toBe(
      'https://docs.example/p0',
    );
  });

  it('keeps the group name as the panel description by source', async () => {
    localStorage.setItem('DocsGPTDocsGapsGroup', 'source');
    respond({ rows: [row({ key: 's1', name: 'Core', source: null })] });
    await render();
    await act(async () =>
      container.querySelector<HTMLTableRowElement>('tbody tr')!.click(),
    );
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(
      dialog.querySelector('[data-slot="sheet-description"]')!.textContent,
    ).toBe('settings.analytics.gaps.groups.source');
  });

  it('opens a group in a side panel whose examples link into Logs', async () => {
    respond({ rows: [row()] });
    await render();
    const first = container.querySelector<HTMLTableRowElement>('tbody tr')!;
    await act(async () => first.click());
    expect(first.getAttribute('aria-current')).toBe('true');
    const dialog = document.body.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain('Installing on Docker');
    const values = Array.from(dialog.querySelectorAll('dd')).map(
      (value) => value.textContent,
    );
    expect(values.slice(0, 2)).toEqual([
      '6',
      'settings.analytics.gaps.share(20%|31)',
    ]);
    const links = Array.from(dialog.querySelectorAll('a')).map((a) =>
      a.getAttribute('href'),
    );
    expect(links).toEqual([
      '/agents/manage/logs/a1?conversation=c1&message=m1#logs',
      '/agents/manage/logs/a1?label=docs_gap#logs',
    ]);
  });

  it('exports the rows on screen as CSV', async () => {
    respond({ rows: [row()] });
    await render();
    const exportButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'settings.analytics.gaps.export',
    )!;
    await act(async () => exportButton.click());
    const [text, fileName] = downloadCsv.mock.calls[0];
    expect(text).toContain('page,/install/docker,Installing on Docker,,6.2');
    expect(fileName).toMatch(
      /^docs-gaps-fintech-bot-page-last_30_days-\d{4}-\d{2}-\d{2}\.csv$/,
    );
  });

  it('says when there are no gaps, with no export button', async () => {
    respond({ rows: [] });
    await render();
    expect(container.textContent).toContain('settings.analytics.gaps.empty');
    expect(container.textContent).not.toContain(
      'settings.analytics.gaps.export',
    );
  });

  it('reloads in place as more answers are analyzed, not while a group is open', async () => {
    // The insights above poll while the sweep labels; a report loaded early
    // must not stay at what was labelled then.
    respond({ rows: [] });
    await render({ labelled: 3 });
    expect(getDocsGaps).toHaveBeenCalledTimes(1);
    respond({ rows: [row()] });
    await render({ labelled: 3 });
    expect(getDocsGaps).toHaveBeenCalledTimes(1);
    await render({ labelled: 9 });
    expect(getDocsGaps).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('Installing on Docker');
    // An open group stays as it is until it is closed.
    const opener = container.querySelector<HTMLElement>('tbody tr')!;
    await act(async () => opener.click());
    respond({ rows: [row({ name: 'Upgrading' })] });
    await render({ labelled: 12 });
    expect(getDocsGaps).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[data-testid="docs-gaps"]')).not.toBeNull();
  });

  it('shows the load error with Retry, and nothing while the agent has it off', async () => {
    getDocsGaps.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({}),
    });
    await render();
    expect(container.querySelector('[role="alert"]')!.textContent).toContain(
      'settings.analytics.gaps.loadError',
    );
    respond({ enabled: false, rows: [] });
    const retry = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(container.querySelector('[data-testid="docs-gaps"]')).toBeNull();
  });

  // The weekly notification links to `#docs-gaps`. The report is unmounted
  // while the insights above it reload (a window change, Retry, a settings
  // save, a renewed token): it scrolls there once per visit, not each time.
  it('brings the report into view once for a #docs-gaps link', async () => {
    respond({ rows: [row()] });
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    let hash = '';
    function Hash() {
      hash = useLocation().hash;
      return null;
    }
    const show = (shown: boolean) =>
      act(async () =>
        root.render(
          <MemoryRouter initialEntries={['/x?a=1#docs-gaps']}>
            {shown && (
              <DocsGaps
                agentId="a1"
                agentName="Fintech bot"
                filterOption="last_30_days"
                hasTopics={false}
              />
            )}
            <Hash />
          </MemoryRouter>,
        ),
      );
    try {
      await show(true);
      await act(async () => undefined);
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      // Ready, then gone while the insights load, then ready again.
      await show(false);
      await show(true);
      await act(async () => undefined);
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(hash).toBe('');
    } finally {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    }
  });

  it("reads the server's topic grouping", async () => {
    respond(examples.gaps);
    await render({ hasTopics: true });
    const cells = Array.from(
      container.querySelectorAll('tbody tr:first-child td'),
    ).map((cell) => cell.textContent);
    expect(cells[0]).toBe('installation');
    expect(cells[1]).toBe('2');
    expect(cells[3]).toBe('settings.analytics.gaps.change.new');
  });
});
