import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';

import type { Agent } from '../../agents/types';
import type { ConversationInsights as Insights } from '../types';
import examples from './fixtures/apiExamples.json';

const store = vi.hoisted(() => ({
  state: { preference: { token: 'token', roles: ['admin'] as string[] } },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
}));

// Keys with their interpolated values, so copy and figures can be checked.
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

// Chart.js needs a canvas; the panel around it is what is tested here. The
// last chart's props are kept, so the figures it is handed can be checked.
const charts = vi.hoisted(() => ({
  props: [] as {
    data: {
      datasets: { label: string; data: number[]; backgroundColor: string }[];
    };
    tooltipCallbacks: {
      label: (item: unknown) => string;
      footer?: (items: unknown[]) => string;
    };
  }[],
}));
vi.mock('../AnalyticsChart', () => ({
  default: (props: (typeof charts.props)[number]) => {
    charts.props.push(props);
    return (
      <div data-testid="chart">
        {props.data.datasets.map((dataset) => dataset.label).join(',')}
      </div>
    );
  },
}));
vi.mock('../DocsGaps', () => ({
  default: (props: { hasTopics: boolean; agentId?: string }) => (
    <div
      data-testid="docs-gaps-stub"
      data-has-topics={String(props.hasTopics)}
    />
  ),
}));

import ConversationInsights from './ConversationInsights';
import { insightsState, type InsightsState } from './format';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const option = (expected: number, rate: number, low: number, high: number) => ({
  expected,
  rate,
  low,
  high,
});

const data = (overrides: Partial<Insights> = {}): Insights => ({
  success: true,
  enabled: true,
  available: true,
  coverage: {
    turns: 120,
    labelled_turns: 118,
    replies: 40,
    labelled_replies: 40,
    conversations: 70,
    labelled_conversations: 61,
    unlabelled_recent_turns: 2,
    unlabelled_older_turns: 0,
  },
  backfill_days: 7,
  labelling_from: '2026-10-13T12:00:00Z',
  languages: { en: 100, ru: 12, other: 6 },
  language_warnings: [],
  one_pick: ['billing', 'installation'],
  overlapping: [],
  totals: {
    answer_status: {
      tier: 'dashboard',
      n: 104,
      options: {
        'fully answered': option(77, 0.741, 0.66, 0.81),
        'partially answered': option(15, 0.14, 0.09, 0.2),
        'not a request': option(14, 0.12, 0.07, 0.18),
      },
    },
    goal_met: {
      tier: 'dashboard',
      n: 61,
      options: { yes: option(49, 0.81, 0.74, 0.87) },
    },
    frustrated: {
      tier: 'dashboard',
      n: 40,
      options: { yes: option(1.2, 0.03, 0.01, 0.06) },
    },
    asks_human: {
      tier: 'dashboard',
      n: 3,
      options: { yes: option(0.3, 0.1, 0, 0.5) },
    },
    gap_type: {
      tier: 'estimated',
      n: 118,
      options: {
        'docs missing': option(12.1, 0.1, 0.07, 0.14),
        'out of scope': option(5.9, 0.05, 0.02, 0.09),
        'not retrieved': option(0, 0, 0, 0),
        none: option(95, 0.8, 0.75, 0.85),
      },
    },
    request_type: {
      tier: 'estimated',
      n: 118,
      options: {
        other: option(4, 0.03, 0.01, 0.07),
        'how-to': option(45, 0.38, 0.31, 0.45),
        troubleshooting: option(28, 0.24, 0.18, 0.31),
      },
    },
    reaction: {
      tier: 'estimated',
      n: 40,
      options: {
        'thanks or confirmation': option(10, 0.25, 0.14, 0.4),
      },
    },
  },
  series: [
    {
      bucket: '2026-10-19',
      labels: {
        answer_status: { n: 12, options: { 'fully answered': 8.7 } },
        reaction: { n: 4, options: { 'thanks or confirmation': 1.1 } },
      },
    },
  ],
  ...overrides,
});

const agent = (actions: string[]): Agent =>
  ({
    id: 'a1',
    name: 'Fintech bot',
    agent_type: 'classic',
    status: 'published',
    allowed_actions: actions,
  }) as unknown as Agent;

describe('ConversationInsights', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    store.state.preference.roles = ['admin'];
    charts.props = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function LocationProbe() {
    const location = useLocation();
    return (
      <span data-testid="location">{location.pathname + location.hash}</span>
    );
  }

  const render = (
    response: Insights | null,
    {
      status = 'ready',
      agentProp,
      onRetry = () => undefined,
      filterOption = 'last_30_days',
      onTurnOn,
      onSetUpTopics,
    }: {
      status?: 'loading' | 'error' | 'ready';
      agentProp?: Agent;
      onRetry?: () => void;
      filterOption?: string;
      onTurnOn?: () => void;
      onSetUpTopics?: () => void;
    } = {},
  ) => {
    const state: InsightsState = insightsState(status, response);
    act(() =>
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/insights/a1']}>
          <ConversationInsights
            state={state}
            data={response}
            agentId={agentProp?.id}
            agent={agentProp}
            filterOption={filterOption}
            onRetry={onRetry}
            onTurnOn={onTurnOn}
            onSetUpTopics={onSetUpTopics}
          />
          <LocationProbe />
        </MemoryRouter>,
      ),
    );
  };

  const emptyState = () =>
    section()!.querySelector<HTMLElement>('[data-slot="empty-state"]');
  const unlabelled = (
    turns: number,
    labelled: number,
    recent: number,
    older: number,
    failed = 0,
  ) =>
    data({
      coverage: {
        ...data().coverage,
        turns,
        labelled_turns: labelled,
        unlabelled_recent_turns: recent,
        unlabelled_older_turns: older,
        failed_turns: failed,
      },
    });

  const section = () => container.querySelector('[data-testid="insights"]');
  const tile = (key: string) =>
    container.querySelector<HTMLElement>(`[data-testid="insight-${key}"]`)!;

  it('shows nothing at all while the server has it off, to an administrator too', () => {
    render(data({ available: false, enabled: false }));
    // Only the test's location probe is drawn.
    expect(container.children).toHaveLength(1);
    expect(section()).toBeNull();
  });

  // IN-20: one honest state each, with its next step, and the intro only
  // above figures.
  it("offers an agent's editors Turn on when the agent has it off", () => {
    const onTurnOn = vi.fn();
    render(data({ enabled: false }), {
      agentProp: agent(['view', 'edit']),
      onTurnOn,
    });
    const empty = emptyState()!;
    expect(empty.textContent).toContain(
      'settings.analytics.insights.off.title',
    );
    expect(empty.textContent).toContain(
      'settings.analytics.insights.off.description',
    );
    expect(section()!.textContent).not.toContain(
      'settings.analytics.insights.description',
    );
    const turnOn = empty.querySelector('button')!;
    expect(turnOn.textContent).toBe('settings.analytics.insights.off.turnOn');
    act(() => turnOn.click());
    // The page's settings panel opens; nothing navigates.
    expect(onTurnOn).toHaveBeenCalledTimes(1);
    expect(
      container.querySelector('[data-testid="location"]')!.textContent,
    ).toBe('/agents/manage/insights/a1');
  });

  it("says the agent has it off, with no button, to someone who can't change it", () => {
    render(data({ enabled: false }), {
      agentProp: agent(['view']),
      onTurnOn: vi.fn(),
    });
    const empty = emptyState()!;
    expect(empty.textContent).toContain(
      'settings.analytics.insights.off.title',
    );
    expect(empty.querySelector('button')).toBeNull();
  });

  it('names the window when it had no conversations', () => {
    render(unlabelled(0, 0, 0, 0), { filterOption: 'last_7_days' });
    expect(emptyState()!.textContent).toContain(
      'settings.analytics.insights.noConversations.last7Days',
    );
    expect(emptyState()!.textContent).toContain(
      'settings.analytics.insights.noConversationsDescription',
    );
    expect(container.querySelector('[data-testid="insight-tiles"]')).toBeNull();
  });

  it('shows how far analysis has come while answers are still to be labelled', () => {
    render(unlabelled(40, 6, 30, 4));
    const empty = emptyState()!;
    expect(empty.textContent).toContain(
      'settings.analytics.insights.analyzing.title',
    );
    // Done of what will be done: older answers are never labelled.
    expect(empty.textContent).toContain(
      'settings.analytics.insights.analyzing.progress(6|36)',
    );
    const bar = empty.querySelector('[data-slot="progress"]')!;
    expect(bar.getAttribute('aria-valuenow')).toBe(String((6 / 36) * 100));
    expect(section()!.textContent).not.toContain(
      'settings.analytics.insights.description',
    );
    expect(container.querySelector('[data-testid="insight-tiles"]')).toBeNull();
  });

  it('says where insights start when every answer is older than the labelling window', () => {
    render(unlabelled(12, 0, 0, 12));
    const empty = emptyState()!;
    expect(empty.textContent).toContain(
      'settings.analytics.insights.olderOnly.title',
    );
    expect(empty.textContent).toContain(
      'settings.analytics.insights.olderOnly.description(13 Oct)',
    );
    expect(empty.querySelector('[data-slot="progress"]')).toBeNull();
  });

  // Answers whose labelling failed for good are not still to come: the
  // page does not wait on them, and says how many there are.
  it('says so when no answer in the window could be analyzed', () => {
    render(unlabelled(3, 0, 0, 0, 3));
    const empty = emptyState()!;
    expect(empty.textContent).toContain(
      'settings.analytics.insights.failedOnly.title',
    );
    expect(empty.textContent).toContain(
      'settings.analytics.insights.failedOnly.description(3)',
    );
    expect(empty.textContent).not.toContain('analyzing');
    expect(empty.textContent).not.toContain('olderOnly');
    expect(empty.querySelector('[data-slot="progress"]')).toBeNull();
    expect(container.querySelector('[data-testid="insight-tiles"]')).toBeNull();
  });

  it('counts answers that could not be analyzed while analyzing', () => {
    render(unlabelled(40, 6, 30, 0, 4));
    expect(emptyState()!.textContent).toContain(
      'settings.analytics.insights.analyzing.progress(6|36)',
    );
    expect(emptyState()!.textContent).toContain(
      'settings.analytics.insights.failed(4)',
    );
  });

  it('shows the error with Retry instead of an empty message', () => {
    const onRetry = vi.fn();
    render(null, { status: 'error', onRetry });
    const alert = section()!.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.analytics.insights.loadError',
    );
    const retry = Array.from(alert.querySelectorAll('button')).find(
      (button) => button.textContent === 'retry',
    )!;
    act(() => retry.click());
    expect(onRetry).toHaveBeenCalled();
  });

  it('shows tile skeletons while loading', () => {
    render(null, { status: 'loading' });
    // Five figure-sized bars in the tiles, then the panels' bars.
    expect(
      section()!.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThanOrEqual(5);
    expect(section()!.textContent).toContain(
      'settings.analytics.insights.stats.fullyAnswered',
    );
    // The fifth tile spans the phone's two columns, as the loaded one does.
    const tiles = section()!.querySelector('.grid')!.children;
    expect(tiles).toHaveLength(5);
    expect(tiles[4].className.split(' ')).toEqual(
      expect.arrayContaining(['col-span-2', 'md:col-span-1']),
    );
    expect(tiles[3].className).not.toContain('col-span');
  });

  // FX-7: the skeleton is the loaded grid's panels, in its order, so no
  // title changes when the figures land.
  it('loads with the panels it will show, in their order', () => {
    const titles = () =>
      Array.from(section()!.querySelectorAll('h2')).map((h) => h.textContent);
    const always = [
      'settings.analytics.insights.panels.answerStatus',
      'settings.analytics.insights.panels.replies',
      'settings.analytics.insights.panels.requestType',
      'settings.analytics.insights.panels.whyNot',
    ];
    render(null, { status: 'loading' });
    expect(titles()).toEqual(always);
    // The fixture has no tags and no topics: the always-there panels only.
    render(data());
    expect(titles()).toEqual(always);
  });

  // The intro paragraph: the description, then the coverage while some
  // answers are still waiting.
  const intro = () => section()!.firstElementChild!.textContent;

  it('counts labelled answers after the description while some are still waiting', () => {
    render(data());
    expect(intro()).toContain('settings.analytics.insights.coverage(118|120)');
    render(
      data({
        coverage: {
          ...data().coverage,
          turns: 118,
          labelled_turns: 118,
          unlabelled_recent_turns: 0,
        },
      }),
    );
    expect(intro()).toContain('settings.analytics.insights.description');
    expect(intro()).not.toContain('settings.analytics.insights.coverage');
  });

  // Only answers the sweep can still label count: older ones never would.
  it('leaves answers older than the labelling window out of the count', () => {
    render(unlabelled(120, 100, 5, 15));
    expect(intro()).toContain('settings.analytics.insights.coverage(100|105)');
    render(unlabelled(120, 100, 0, 20));
    expect(intro()).not.toContain('settings.analytics.insights.coverage');
    expect(
      container.querySelector('[data-testid="insight-tiles"]'),
    ).not.toBeNull();
  });

  it('notes answers that could not be analyzed beside the figures', () => {
    render(unlabelled(12, 11, 0, 0, 1));
    expect(
      container.querySelector('[data-testid="insight-tiles"]'),
    ).not.toBeNull();
    expect(intro()).not.toContain('settings.analytics.insights.coverage');
    expect(intro()).toContain('settings.analytics.insights.failed(1)');
    render(unlabelled(120, 100, 5, 0, 15));
    expect(intro()).toContain('settings.analytics.insights.coverage(100|105)');
    expect(intro()).toContain('settings.analytics.insights.failed(15)');
    // None failed, or an older server that does not say: no note.
    render(unlabelled(120, 100, 0, 20));
    expect(intro()).not.toContain('settings.analytics.insights.failed');
    render(data());
    expect(intro()).not.toContain('settings.analytics.insights.failed');
  });

  it('gives every headline tile a rate and its own denominator, no range', () => {
    render(data());
    expect(tile('fullyAnswered').textContent).toContain('74%');
    expect(tile('fullyAnswered').textContent).toContain(
      'settings.analytics.insights.sub.ofQuestions(104)',
    );
    expect(tile('goalMet').textContent).toContain(
      'settings.analytics.insights.sub.ofConversations(61)',
    );
    expect(tile('frustrated').textContent).toContain(
      'settings.analytics.insights.sub.ofReplies(40)',
    );
    // Docs gaps: an expected count, never decimals.
    expect(tile('docsGaps').textContent).toContain('12');
    // Five tiles: on the phone's two columns the last spans both rather
    // than sit alone; from md it is one tile again.
    expect(tile('docsGaps').className.split(' ')).toEqual(
      expect.arrayContaining(['col-span-2', 'md:col-span-1']),
    );
    expect(tile('asksHuman').className).not.toContain('col-span');
    expect(tile('docsGaps').textContent).toContain(
      'settings.analytics.insights.sub.inAnswers(118)',
    );
    expect(
      container.querySelector('[data-testid="insight-tiles"]')!.textContent,
    ).not.toContain('–');
    // A hint on each tile, and no badge on any.
    expect(tile('goalMet').title).toBe(
      'settings.analytics.insights.stats.goalMetHint',
    );
    expect(
      container
        .querySelector('[data-testid="insight-tiles"]')!
        .querySelector('[data-slot="badge"]'),
    ).toBeNull();
  });

  it('shows no figure for a tiny sample, only how many so far', () => {
    render(data());
    expect(tile('asksHuman').textContent).toContain('—');
    expect(tile('asksHuman').textContent).toContain(
      'settings.analytics.insights.notEnough(3)',
    );
    expect(tile('asksHuman').textContent).not.toContain('10%');
  });

  it('draws the bar panels with no badge, and the docs-gap report', () => {
    render(data());
    // Every figure is an estimate, said once in the intro.
    expect(section()!.querySelector('[data-slot="badge"]')).toBeNull();
    const requestType = listNamed(
      'settings.analytics.insights.panels.requestType',
    )!;
    const whyNot = listNamed('settings.analytics.insights.panels.whyNot')!;
    // "none" and zero-mass deferred types are not drawn.
    expect(
      Array.from(whyNot.querySelectorAll('li .sr-only')).map(
        (text) => text.textContent,
      ),
    ).toEqual([
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.docsMissing|10%)',
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.outOfScope|5%)',
    ]);
    const requests = Array.from(
      requestType.querySelectorAll('li .sr-only'),
    ).map((text) => text.textContent);
    expect(requests[0]).toContain('requestType.howTo');
    expect(requests[2]).toContain('requestType.other');
    expect(
      container.querySelector('[data-testid="docs-gaps-stub"]'),
    ).not.toBeNull();
  });

  it('names docs missing "Docs gap" beside search misses too, as Logs does', () => {
    const response = data();
    response.totals.gap_type!.options['not retrieved'] = option(
      4,
      0.03,
      0.01,
      0.07,
    );
    render(response);
    const whyNot = listNamed('settings.analytics.insights.panels.whyNot')!;
    expect(
      Array.from(whyNot.querySelectorAll('li .sr-only')).map(
        (text) => text.textContent,
      ),
    ).toEqual([
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.docsMissing|10%)',
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.outOfScope|5%)',
      'settings.analytics.insights.panels.barLabel(settings.analytics.insights.options.gapType.notRetrieved|3%)',
    ]);
  });

  it('puts answer status and how users replied first, in that order', () => {
    render(data());
    const grid = tile('answer-status').parentElement!;
    expect(
      Array.from(grid.children)
        .slice(0, 2)
        .map((panel) => panel.getAttribute('data-testid')),
    ).toEqual(['insight-answer-status', 'insight-replies']);
  });

  it('waits for enough replies before showing how users replied', () => {
    const response = data();
    response.totals.reaction.n = 4;
    render(response);
    expect(tile('replies').querySelector('[data-testid="chart"]')).toBeNull();
    expect(tile('replies').textContent).toContain(
      'settings.analytics.insights.notEnoughReplies',
    );
  });

  it('opens with its description, not a heading, as a page of its own', () => {
    render(data());
    expect(section()!.firstElementChild!.tagName).toBe('P');
    expect(intro()).toContain('settings.analytics.insights.description');
  });

  // Settings › Insights draws the description in its page toolbar.
  it('leaves the description to the page when told to', () => {
    act(() =>
      root.render(
        <MemoryRouter>
          <ConversationInsights
            state="ready"
            data={data()}
            filterOption="last_30_days"
            onRetry={() => undefined}
            intro={false}
          />
        </MemoryRouter>,
      ),
    );
    expect(section()!.textContent).not.toContain(
      'settings.analytics.insights.description',
    );
    expect(
      section()!.querySelector('[data-testid="insight-replies"]'),
    ).not.toBeNull();
  });

  const lists = () => Array.from(section()!.querySelectorAll('[role="list"]'));
  const listNamed = (name: string) =>
    lists().find((list) => list.getAttribute('aria-label') === name);
  const P = 'settings.analytics.insights.panels';
  const topicTotals = (response: Insights) => {
    response.totals.topic_effective = {
      tier: 'experimental',
      n: 118,
      options: {
        'none of these': option(13, 0.11, 0.06, 0.18),
        installation: option(36, 0.31, 0.23, 0.39),
      },
    };
  };

  it('splits Topics into one half per kind, a new overlapping topic without a figure', () => {
    const response = data({
      overlapping: [
        { id: 'a1b2c3d4', name: 'Pricing question' },
        { id: 'deadbeef', name: 'Wants a refund' },
      ],
    });
    topicTotals(response);
    response.totals['tag:a1b2c3d4'] = {
      tier: 'dashboard',
      n: 61,
      options: { yes: option(13, 0.22, 0.13, 0.33) },
    };
    render(response, { agentProp: agent(['view', 'edit']) });
    expect(section()!.querySelector('[data-slot="badge"]')).toBeNull();
    const onePick = listNamed('agents.form.analytics.groups.onePick')!;
    const onePickRows = Array.from(onePick.querySelectorAll('li'));
    expect(onePickRows[0].textContent).toContain('installation');
    expect(onePickRows[1].textContent).toContain(`${P}.noneOfThese`);
    const overlap = listNamed('agents.form.analytics.groups.overlap')!;
    const overlapRows = Array.from(overlap.querySelectorAll('li'));
    expect(overlapRows[0].textContent).toContain('22%');
    expect(overlapRows[1].textContent).toContain('—');
    expect(overlapRows[1].querySelector('.sr-only')!.textContent).toBe(
      `${P}.barLabelNone(Wants a refund)`,
    );
    // Both halves sit in one panel spanning the grid.
    const panel = onePick.closest('[data-slot="card"]')!;
    expect(panel).toBe(overlap.closest('[data-slot="card"]'));
    expect(panel.className).toContain('xl:col-span-2');
    expect(panel.querySelector('h2')!.textContent).toBe(`${P}.topics`);
    expect(panel.textContent).toContain(`${P}.overlapNote`);
    expect(
      container
        .querySelector('[data-testid="docs-gaps-stub"]')!
        .getAttribute('data-has-topics'),
    ).toBe('true');
  });

  it('lays one kind alone across both columns, without halves', () => {
    const response = data();
    topicTotals(response);
    render(response, { agentProp: agent(['view', 'edit']) });
    const topics = listNamed(`${P}.topics`)!;
    expect(topics.className).toContain('xl:grid-cols-2');
    expect(listNamed('agents.form.analytics.groups.onePick')).toBeUndefined();
    expect(section()!.textContent).not.toContain(`${P}.overlapNote`);

    const overlapOnly = data({
      overlapping: [{ id: 'a1b2c3d4', name: 'Pricing question' }],
    });
    render(overlapOnly, { agentProp: agent(['view', 'edit']) });
    expect(listNamed(`${P}.topics`)!.textContent).toContain('Pricing question');
    expect(section()!.textContent).toContain(`${P}.overlapNote`);
  });

  it('shows editors of an agent without topics the way to set them up', () => {
    const onSetUpTopics = vi.fn();
    const response = data({ one_pick: [] });
    render(response, { agentProp: agent(['view', 'edit']), onSetUpTopics });
    expect(section()!.textContent).toContain(`${P}.noTopics.title`);
    act(() =>
      Array.from(section()!.querySelectorAll('button'))
        .find((b) => b.textContent === `${P}.noTopics.action`)!
        .click(),
    );
    expect(onSetUpTopics).toHaveBeenCalledTimes(1);

    // A viewer, or an agent whose topics just have no figures yet, gets no panel.
    render(response, { agentProp: agent(['view']), onSetUpTopics });
    expect(section()!.textContent).not.toContain(`${P}.noTopics.title`);
    render(data({ one_pick: ['billing', 'setup'] }), {
      agentProp: agent(['view', 'edit']),
      onSetUpTopics,
    });
    expect(section()!.textContent).not.toContain(`${P}.noTopics.title`);
    expect(section()!.textContent).not.toContain(`${P}.topics`);
  });

  it('pairs request type beside why not, then Topics across the row', () => {
    const response = data({
      overlapping: [{ id: 'a1b2c3d4', name: 'Pricing' }],
    });
    topicTotals(response);
    render(response, { agentProp: agent(['view', 'edit']) });
    const names = lists().map((list) =>
      list.getAttribute('aria-label')!.split('.').pop(),
    );
    expect(names.slice(-4)).toEqual([
      'requestType',
      'whyNot',
      'onePick',
      'overlap',
    ]);
    const whyNot = listNamed(`${P}.whyNot`)!;
    expect(whyNot.closest('.xl\\:col-span-2')).toBeNull();
    expect(
      listNamed(`${P}.requestType`)!.closest('.xl\\:col-span-2'),
    ).toBeNull();
  });

  it('says once when weaker languages make some labels less reliable', () => {
    render(data({ language_warnings: ['answer_status', 'topic_effective'] }));
    const notes = section()!.querySelectorAll('[role="note"]');
    expect(notes).toHaveLength(1);
    expect(notes[0].textContent).toBe(
      'settings.analytics.insights.languageNote(15%|Russian and settings.analytics.insights.otherLanguages|Settings.analytics.insights.labelNamesInline.answer_status and settings.analytics.insights.labelNamesInline.topic_effective)',
    );
    render(data());
    expect(section()!.querySelector('[role="note"]')).toBeNull();
  });

  it("reads the server's own response: small samples show no figure yet", () => {
    render(examples.insights as unknown as Insights, {
      agentProp: agent(['view', 'edit']),
    });
    expect(tile('fullyAnswered').textContent).toContain(
      'settings.analytics.insights.notEnough(3)',
    );
    expect(tile('docsGaps').textContent).toContain(
      'settings.analytics.insights.notEnough(4)',
    );
    // Only the tags panel lists rows under the floor: each tag says "—".
    const lists = section()!.querySelectorAll('[role="list"]');
    expect(lists).toHaveLength(1);
    expect(lists[0].textContent).toContain('Pricing question');
    expect(lists[0].textContent).toContain('—');
    expect(
      section()!.textContent!.match(
        /settings\.analytics\.insights\.notEnoughShort/g,
      )!.length,
    ).toBe(4);
    // Every panel's empty state is the size for inside a panel.
    const empties = Array.from(
      section()!.querySelectorAll('[data-slot="empty-state"]'),
    );
    expect(empties.length).toBeGreaterThanOrEqual(4);
    expect(empties.map((empty) => empty.getAttribute('data-size'))).toEqual(
      empties.map(() => 'sm'),
    );
    expect(section()!.querySelector('[role="note"]')!.textContent).toContain(
      'Russian',
    );
  });
});
