import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { ConversationInsights } from '../types';

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

// The chart's props, so the figures each panel hands it can be checked.
const chart = vi.hoisted(() => ({
  props: null as null | {
    data: {
      datasets: { label: string; data: number[]; backgroundColor: string }[];
    };
    share?: boolean;
    tooltipCallbacks: {
      label: (item: unknown) => string;
      footer: (items: unknown[]) => string;
    };
  },
}));
vi.mock('../AnalyticsChart', () => ({
  default: (props: NonNullable<typeof chart.props>) => {
    chart.props = props;
    return (
      <div data-testid="chart">
        {props.data.datasets.map((dataset) => dataset.label).join(',')}
      </div>
    );
  },
}));

import ImplicitFeedbackPanel from './ImplicitFeedbackPanel';
import SentimentPanel from './SentimentPanel';
import ShareBars from './ShareBars';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const insights = (n: number): ConversationInsights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: 10,
    labelled_turns: 10,
    replies: n,
    labelled_replies: n,
    conversations: 5,
    labelled_conversations: 5,
  },
  languages: {},
  language_warnings: [],
  tags: [],
  totals: {
    reaction: {
      tier: 'estimated',
      n,
      options: {
        'thanks or confirmation': {
          expected: 4,
          rate: 0.3,
          low: 0.2,
          high: 0.5,
        },
        complaint: { expected: 1, rate: 0.1, low: 0.02, high: 0.2 },
      },
    },
  },
  series: [
    {
      bucket: '2026-10-18',
      labels: {
        reaction: {
          n: 6,
          options: {
            'thanks or confirmation': 2,
            're-ask': 1,
            'correction or pushback': 0.5,
            complaint: 0.25,
            'new question': 3,
          },
        },
        sentiment: {
          n: 4,
          options: { positive: 2.4, neutral: 1, negative: 0.6 },
        },
      },
    },
    // A day with no replies: nothing to share out.
    {
      bucket: '2026-10-19',
      labels: {
        reaction: { n: 0, options: {} },
        sentiment: { n: 0, options: { positive: 0, neutral: 0, negative: 0 } },
      },
    },
  ],
});

/** Each dataset's label and its points, rounded to two places. */
const drawn = () =>
  chart.props!.data.datasets.map((dataset) => [
    dataset.label,
    dataset.data.map((value) => Math.round(value * 100) / 100),
  ]);

describe('insight panels', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    chart.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("draws implicit feedback as each day's share of its replies, pushback and complaint summed", () => {
    act(() => root.render(<ImplicitFeedbackPanel data={insights(40)} />));
    // Of the day's 6 replies; the neutral kinds (a new question) are the
    // undrawn gap, and a day without replies stays an empty column.
    expect(drawn()).toEqual([
      ['settings.analytics.insights.options.reaction.thanks', [0.33, 0]],
      ['settings.analytics.insights.options.reaction.reAsk', [0.17, 0]],
      [
        'settings.analytics.insights.options.reaction.pushbackOrComplaint',
        [0.13, 0],
      ],
    ]);
    expect(chart.props!.share).toBe(true);
    // The tooltip reads the share, and the day's replies as a count.
    const { label, footer } = chart.props!.tooltipCallbacks;
    expect(
      label({ dataset: { label: 'Thanks' }, raw: 2 / 6, dataIndex: 0 }),
    ).toBe('settings.analytics.insights.panels.tooltipShare(Thanks|33%)');
    expect(footer([{ dataIndex: 0 }])).toBe(
      'settings.analytics.insights.panels.ofReplies(6)',
    );
    // Every figure is an estimate, said once in the intro: no badge.
    expect(container.querySelector('[data-slot="badge"]')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
  });

  it("draws sentiment as each day's share of its replies, filling the column", () => {
    act(() =>
      root.render(
        <SentimentPanel
          data={{
            ...insights(40),
            totals: {
              sentiment: { tier: 'estimated', n: 40, options: {} },
            },
          }}
        />,
      ),
    );
    expect(drawn()).toEqual([
      ['settings.analytics.insights.options.sentiment.positive', [0.6, 0]],
      ['settings.analytics.insights.options.sentiment.neutral', [0.25, 0]],
      ['settings.analytics.insights.options.sentiment.negative', [0.15, 0]],
    ]);
    expect(chart.props!.share).toBe(true);
    const { label, footer } = chart.props!.tooltipCallbacks;
    expect(
      label({ dataset: { label: 'Positive' }, raw: 0.6, dataIndex: 0 }),
    ).toBe('settings.analytics.insights.panels.tooltipShare(Positive|60%)');
    expect(footer([{ dataIndex: 0 }])).toBe(
      'settings.analytics.insights.panels.ofReplies(4)',
    );
  });

  it('waits for enough replies before drawing implicit feedback', () => {
    act(() => root.render(<ImplicitFeedbackPanel data={insights(4)} />));
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    // The empty state at the size for inside a panel.
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.getAttribute('data-size')).toBe('sm');
    expect(empty.textContent).toContain(
      'settings.analytics.insights.notEnoughReplies',
    );
  });

  it('draws each bar as a Progress to its rate, with the figure alone beside it', () => {
    act(() =>
      root.render(
        <ShareBars
          ariaLabel="Request type"
          rows={[
            { key: 'how-to', label: 'How-to', rate: 0.38 },
            { key: 'tag', label: 'Pricing question' },
          ]}
        />,
      ),
    );
    const list = container.querySelector('[role="list"]')!;
    expect(list.getAttribute('aria-label')).toBe('Request type');
    const [howTo, tag] = Array.from(list.querySelectorAll('li'));
    const bar = howTo.querySelector<HTMLElement>('[data-slot="progress"]')!;
    expect(bar.getAttribute('data-variant')).toBe('default');
    expect(
      howTo
        .querySelector<HTMLElement>('[data-slot="progress-indicator"]')!
        .style.getPropertyValue('--progress'),
    ).toBe('38%');
    // No range, no whiskers.
    expect(howTo.textContent).toContain('38%');
    expect(howTo.textContent).not.toContain('–');
    expect(howTo.querySelector('.bg-foreground\\/70')).toBeNull();
    // Assistive tech reads one run per row: the label and the figure; the
    // drawing is hidden from it.
    expect(howTo.querySelector('.sr-only')!.textContent).toBe(
      'settings.analytics.insights.panels.barLabel(How-to|38%)',
    );
    expect(bar.closest('[aria-hidden="true"]')).not.toBeNull();
    // A row with no figure yet: a dash and an empty track.
    expect(tag.textContent).toContain('—');
    expect(
      tag
        .querySelector<HTMLElement>('[data-slot="progress-indicator"]')!
        .style.getPropertyValue('--progress'),
    ).toBe('0%');
    expect(tag.querySelector('.sr-only')!.textContent).toBe(
      'settings.analytics.insights.panels.barLabelNone(Pricing question)',
    );
  });

  it('wraps a long label beside the track from sm instead of cutting it', () => {
    act(() =>
      root.render(
        <ShareBars
          ariaLabel="Why not fully answered"
          rows={[
            {
              key: 'needs account data',
              label: 'Needs account access or staff',
              rate: 0.06,
            },
          ]}
        />,
      ),
    );
    const row = container.querySelector('li')!;
    expect(row.className.split(' ')).toEqual(
      expect.arrayContaining(['flex-col', 'sm:flex-row', 'sm:min-h-7']),
    );
    expect(row.className.split(' ')).not.toContain('sm:h-7');
    const label = row.querySelector<HTMLElement>('[aria-hidden="true"]')!;
    expect(label.textContent).toBe('Needs account access or staff');
    expect(label.className).toContain('wrap-break-word');
    expect(label.className).toContain('sm:w-40');
    expect(label.className).not.toContain('truncate');
  });
});
