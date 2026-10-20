import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

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
    json: () => Promise.resolve({ success: true, enabled: true, ...body }),
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
    expect(text).toContain('page,/install/docker,6.2');
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
