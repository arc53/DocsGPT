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
      labels: string[];
      datasets: { label: string; data: number[]; backgroundColor: string }[];
    };
    columnTooltip?: boolean;
    diverging?: boolean;
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

import AnswerStatusPanel from './AnswerStatusPanel';
import RepliesPanel from './RepliesPanel';
import ShareBars from './ShareBars';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const figure = (rate: number, expected = 0) => ({
  expected,
  rate,
  low: 0,
  high: 1,
});

type Bucket = ConversationInsights['series'][number];

/** A week of the series: its answer status, reaction and sentiment. */
const week = (
  bucket: string,
  bucket_end: string,
  { questions = 0, replies = 0 }: { questions?: number; replies?: number },
): Bucket => ({
  bucket,
  bucket_end,
  labels: {
    answer_status: {
      n: questions + 1,
      options: {
        'fully answered': questions * 0.5,
        'partially answered': questions * 0.25,
        'declined, no information': questions * 0.125,
        'asked a clarifying question': questions * 0.125,
        // A greeting: never one of the questions.
        'not a request': 1,
      },
    },
    reaction: {
      n: replies,
      options: {
        'thanks or confirmation': replies * 0.1,
        're-ask': replies * 0.2,
        'correction or pushback': replies * 0.05,
        complaint: replies * 0.05,
        'new question': replies * 0.6,
      },
    },
    sentiment: {
      n: replies,
      options: {
        positive: replies * 0.1,
        neutral: replies * 0.7,
        negative: replies * 0.2,
      },
    },
  },
});

const insights = ({
  replies = 40,
  questions = 60,
  series = [
    week('2026-10-01', '2026-10-04', { questions: 20, replies: 12 }),
    week('2026-10-05', '2026-10-11', { questions: 0, replies: 0 }),
    week('2026-10-12', '2026-10-18', { questions: 25, replies: 14 }),
    week('2026-10-19', '2026-10-24', { questions: 15, replies: 14 }),
  ],
  previous,
}: {
  replies?: number;
  questions?: number;
  series?: Bucket[];
  previous?: ConversationInsights['previous'];
} = {}): ConversationInsights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: questions,
    labelled_turns: questions,
    replies,
    labelled_replies: replies,
    conversations: 30,
    labelled_conversations: 30,
    unlabelled_recent_turns: 0,
    unlabelled_older_turns: 0,
  },
  backfill_days: 30,
  labelling_from: '2026-09-24T12:00:00Z',
  languages: {},
  language_warnings: [],
  one_pick: [],
  overlapping: [],
  totals: {
    answer_status: {
      tier: 'dashboard',
      n: questions,
      options: {
        'fully answered': figure(0.5),
        'partially answered': figure(0.25),
        'declined, no information': figure(0.125),
        'asked a clarifying question': figure(0.125),
      },
    },
    reaction: {
      tier: 'estimated',
      n: replies,
      options: {
        'thanks or confirmation': figure(0.1),
        're-ask': figure(0.2),
        'correction or pushback': figure(0.05),
        complaint: figure(0.05),
        'new question': figure(0.6),
      },
    },
    sentiment: {
      tier: 'dashboard',
      n: replies,
      options: {
        positive: figure(0.1),
        neutral: figure(0.7),
        negative: figure(0.2),
      },
    },
  },
  previous,
  bucket_unit: 'week',
  series,
});

/** Each dataset's label and its points, rounded to two places. */
const drawn = () =>
  chart.props!.data.datasets.map((dataset) => [
    dataset.label,
    dataset.data.map((value) => Math.round(value * 100) / 100),
  ]);

const P = 'settings.analytics.insights';

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

  const headline = () =>
    container.querySelector<HTMLElement>('[data-testid="insight-headline"]')!;

  it("stacks each week's questions by outcome as counts, greetings left out", () => {
    act(() => root.render(<AnswerStatusPanel data={insights()} />));
    expect(chart.props!.data.labels).toEqual([
      '1–4 Oct',
      '5–11 Oct',
      '12–18 Oct',
      '19–24 Oct',
    ]);
    // A quiet week is a short column, an empty one none at all.
    expect(drawn()).toEqual([
      [`${P}.options.answerStatus.fullyAnswered`, [10, 0, 12.5, 7.5]],
      [`${P}.options.answerStatus.partiallyAnswered`, [5, 0, 6.25, 3.75]],
      [`${P}.options.answerStatus.declined`, [2.5, 0, 3.13, 1.88]],
      [`${P}.options.answerStatus.clarifying`, [2.5, 0, 3.13, 1.88]],
    ]);
    // "Said it didn't know" is the neutral grey, not a failure's red.
    expect(
      chart.props!.data.datasets.map((dataset) => dataset.backgroundColor),
    ).toEqual(['#079455', '#ca8a04', '#6b6b6b', '#2563eb']);
    expect(chart.props!.columnTooltip).toBe(true);
    expect(chart.props!.diverging).toBeFalsy();
    const { label, footer } = chart.props!.tooltipCallbacks;
    expect(label({ dataset: { label: 'Partially answered' }, raw: 6.25 })).toBe(
      `${P}.panels.tooltipItem(Partially answered|6)`,
    );
    // The week's four outcomes, not its greeting.
    expect(footer([{ dataIndex: 0 }])).toBe(`${P}.panels.ofQuestions(20)`);
    // The headline: the period's figure, its denominator and its mix.
    expect(headline().textContent).toContain('50%');
    expect(headline().textContent).toContain(`${P}.sub.ofQuestions(60)`);
    expect(
      Array.from(headline().querySelectorAll('li')).map((li) => li.textContent),
    ).toEqual([
      `${P}.options.answerStatus.fullyAnswered50%`,
      `${P}.options.answerStatus.partiallyAnswered25%`,
      `${P}.options.answerStatus.declined13%`,
      `${P}.options.answerStatus.clarifying13%`,
    ]);
    // No earlier period to compare with.
    expect(headline().querySelector('[data-direction]')).toBeNull();
  });

  it('compares the headline with the previous period once it has enough', () => {
    const previous = (n: number) => ({
      answer_status: {
        tier: 'dashboard' as const,
        n,
        options: { 'fully answered': figure(0.62) },
      },
    });
    act(() =>
      root.render(
        <AnswerStatusPanel data={insights({ previous: previous(40) })} />,
      ),
    );
    const change = headline().querySelector('[data-direction]')!;
    expect(change.getAttribute('data-direction')).toBe('down');
    expect(change.textContent).toBe(`${P}.headline.previous(62%)`);
    act(() =>
      root.render(
        <AnswerStatusPanel data={insights({ previous: previous(9) })} />,
      ),
    );
    expect(headline().querySelector('[data-direction]')).toBeNull();
  });

  it('shows the outcomes as bars when too few weeks hold enough to chart', () => {
    const series = [
      week('2026-10-12', '2026-10-18', { questions: 50, replies: 30 }),
      week('2026-10-19', '2026-10-24', { questions: 10, replies: 10 }),
    ];
    act(() => root.render(<AnswerStatusPanel data={insights({ series })} />));
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    const list = container.querySelector(
      `[role="list"][aria-label="${P}.panels.answerStatus"]`,
    )!;
    expect(
      Array.from(list.querySelectorAll('.sr-only')).map(
        (row) => row.textContent,
      ),
    ).toEqual([
      `${P}.panels.barLabel(${P}.options.answerStatus.fullyAnswered|50%)`,
      `${P}.panels.barLabel(${P}.options.answerStatus.partiallyAnswered|25%)`,
      `${P}.panels.barLabel(${P}.options.answerStatus.declined|13%)`,
      `${P}.panels.barLabel(${P}.options.answerStatus.clarifying|13%)`,
    ]);
    expect(
      Array.from(list.querySelectorAll('[data-slot="progress"]')).map((bar) =>
        bar.getAttribute('data-variant'),
      ),
    ).toEqual(['success', 'warning', 'muted', 'info']);
    // The headline without its strip: the bars are the mix.
    expect(headline().querySelector('li')).toBeNull();
  });

  it('waits for enough questions before drawing answer status', () => {
    act(() =>
      root.render(<AnswerStatusPanel data={insights({ questions: 6 })} />),
    );
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    expect(container.textContent).toContain(`${P}.notEnoughShort`);
  });

  it('draws replies that helped up from zero and those that did not down, as counts', () => {
    act(() => root.render(<RepliesPanel data={insights()} />));
    expect(drawn()).toEqual([
      [`${P}.options.reaction.thanks`, [1.2, 0, 1.4, 1.4]],
      [`${P}.options.reaction.reAsk`, [-2.4, 0, -2.8, -2.8]],
      // Pushback and complaint summed.
      [`${P}.options.reaction.pushbackOrComplaint`, [-1.2, 0, -1.4, -1.4]],
    ]);
    expect(chart.props!.diverging).toBe(true);
    expect(chart.props!.columnTooltip).toBe(true);
    const { label, footer } = chart.props!.tooltipCallbacks;
    expect(label({ dataset: { label: 'Asked again' }, raw: -2.8 })).toBe(
      `${P}.panels.tooltipItem(Asked again|3)`,
    );
    expect(footer([{ dataIndex: 2 }])).toBe(`${P}.panels.ofReplies(14)`);
    // Asked again, pushback and complaint: 30% of the period's replies,
    // with moving on, never drawn, named in the mix.
    expect(headline().textContent).toContain('30%');
    expect(headline().textContent).toContain(
      `${P}.headline.askedAgainOrPushedBack`,
    );
    expect(
      Array.from(headline().querySelectorAll('li')).map((li) => li.textContent),
    ).toEqual([
      `${P}.options.reaction.thanks10%`,
      `${P}.options.reaction.reAsk20%`,
      `${P}.options.reaction.pushbackOrComplaint10%`,
      `${P}.options.reaction.movedOn60%`,
    ]);
    expect(container.textContent).toContain(`${P}.panels.notDrawnMovedOn`);
  });

  it('switches the same replies to their tone', () => {
    act(() => root.render(<RepliesPanel data={insights()} />));
    const tone = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find((item) => item.textContent === `${P}.panels.tone`)!;
    act(() => tone.click());
    expect(drawn()).toEqual([
      [`${P}.options.sentiment.positive`, [1.2, 0, 1.4, 1.4]],
      [`${P}.options.sentiment.negative`, [-2.4, 0, -2.8, -2.8]],
    ]);
    expect(headline().textContent).toContain('20%');
    expect(headline().textContent).toContain(`${P}.options.sentiment.negative`);
    expect(container.textContent).toContain(`${P}.panels.notDrawnNeutral`);
  });

  it('shows reaction and tone as bars when too few weeks hold enough replies', () => {
    const series = [
      week('2026-10-12', '2026-10-18', { questions: 30, replies: 30 }),
      week('2026-10-19', '2026-10-24', { questions: 30, replies: 10 }),
    ];
    act(() => root.render(<RepliesPanel data={insights({ series })} />));
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    expect(container.querySelector('[data-slot="toggle-group"]')).toBeNull();
    const named = (name: string) =>
      container.querySelector(
        `[role="list"][aria-label="${P}.panels.${name}"]`,
      );
    // Each bar in its meaning's colour, as in the chart: the neutral kind grey.
    const variants = (name: string) =>
      Array.from(named(name)!.querySelectorAll('[data-slot="progress"]')).map(
        (bar) => bar.getAttribute('data-variant'),
      );
    expect(variants('reaction')).toEqual([
      'success',
      'warning',
      'destructive',
      'muted',
    ]);
    expect(variants('tone')).toEqual(['success', 'muted', 'destructive']);
    expect(headline().textContent).toContain('30%');
  });

  it('waits for enough replies before drawing how users replied', () => {
    act(() => root.render(<RepliesPanel data={insights({ replies: 4 })} />));
    expect(container.querySelector('[data-testid="chart"]')).toBeNull();
    // The empty state at the size for inside a panel.
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.getAttribute('data-size')).toBe('sm');
    expect(empty.textContent).toContain(`${P}.notEnoughReplies`);
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
