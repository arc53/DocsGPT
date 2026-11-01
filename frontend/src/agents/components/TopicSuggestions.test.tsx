import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { DrafterEvent, DrafterRequest } from '../../drafter/drafterApi';
import type { TopicsProposal, TopicsStatus } from '../../drafter/topicsDraft';
import type { AnalyticsConfig } from '../types';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Interpolations show as `key(a=1,b=2)`, so counts and names can be checked.
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      const args = Object.entries(opts)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${String(value)}`)
        .join(',');
      return args ? `${key}(${args})` : key;
    },
  }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

const getTopicFolders = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getTopicFolders: (...args: unknown[]) => getTopicFolders(...args),
  },
}));

const mocks = vi.hoisted(() => ({
  drafterEnabled: true,
  status: null as TopicsStatus | null,
  statusCalls: [] as string[],
  scripts: [] as DrafterEvent[][],
  requests: [] as DrafterRequest[],
}));
vi.mock('../../drafter/useDrafterConfig', () => ({
  loadDrafterConfig: () =>
    Promise.resolve({
      enabled: mocks.drafterEnabled,
      model: null,
      reason: mocks.drafterEnabled ? null : 'disabled',
    }),
}));
vi.mock('../../drafter/topicsDraft', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../drafter/topicsDraft')>()),
  getTopicsStatus: (agentId: string) => {
    mocks.statusCalls.push(agentId);
    return Promise.resolve(mocks.status);
  },
}));
vi.mock('../../drafter/drafterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../drafter/drafterApi')>()),
  streamDrafter: async (
    request: DrafterRequest,
    _token: string | null,
    onEvent: (event: DrafterEvent) => void,
  ) => {
    mocks.requests.push(JSON.parse(JSON.stringify(request)));
    (mocks.scripts.shift() ?? [{ type: 'end' }]).forEach(onEvent);
  },
}));

import InsightsSettingsBody from './InsightsSettingsBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const T = 'drafter.topics';

const PROPOSAL: TopicsProposal = {
  message: 'Most questions are about parcels.',
  sample: {
    questions: 300,
    conversations: 120,
    days: 30,
    unmatched: { before: 0.41, after: 0.12, questions: 100 },
  },
  topics: [
    {
      id: 't1',
      name: 'Delivery delays',
      description: 'Late or stuck parcels.',
      overlap: false,
      share: 0.31,
      share_kind: 'measured',
      similar_to: null,
      note: null,
    },
    {
      id: 't2',
      name: 'Refunds',
      description: 'Refunds and claims.',
      overlap: false,
      share: 0.14,
      share_kind: 'estimate',
      similar_to: 'Billing',
      note: 'A third of these are in Billing today.',
    },
    {
      id: 't3',
      name: 'Bug report',
      description: 'Errors and crashes.',
      overlap: true,
      share: 0.05,
      share_kind: 'measured',
      similar_to: null,
      note: null,
    },
  ],
  left_out: [{ name: 'Packaging', reason: 'Your shipping folder covers it.' }],
  capacity: { one_per_question_free: 1, overlapping_free: 20, pushes_out: [] },
};

const FOLDERS = [
  { name: 'shipping', description: 'Pages such as: Rates' },
  { name: 'returns', description: 'Pages such as: Labels' },
];

let latest: AnalyticsConfig | undefined;

function Harness({
  disabled = false,
  agentId = 'a1',
  initial,
  maxTopics = 15,
}: {
  disabled?: boolean;
  agentId?: string;
  initial?: AnalyticsConfig;
  maxTopics?: number;
}) {
  const [value, setValue] = useState<AnalyticsConfig | undefined>(initial);
  return (
    <InsightsSettingsBody
      value={value}
      onChange={(next) => {
        latest = next;
        setValue(next);
      }}
      agentId={agentId}
      maxTopics={maxTopics}
      maxOverlapping={20}
      disabled={disabled}
      token="tok"
    />
  );
}

describe('topic suggestions in the Insights settings', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    latest = undefined;
    mocks.drafterEnabled = true;
    mocks.status = { available: true, conversations: 42, needed: 10 };
    mocks.statusCalls = [];
    mocks.scripts = [];
    mocks.requests = [];
    getTopicFolders.mockReset();
    getTopicFolders.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, folders: FOLDERS }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (props: Parameters<typeof Harness>[0] = {}) => {
    await act(async () => root.render(<Harness {...props} />));
  };
  const button = (text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (el) => el.textContent?.startsWith(text),
    );
  const card = () =>
    container.querySelector<HTMLElement>('[data-testid="topic-suggestions"]');
  const suggestion = (id: string) =>
    card()!.querySelector<HTMLElement>(`[data-suggestion="${id}"]`)!;
  const run = async (events: DrafterEvent[]) => {
    mocks.scripts.push(events);
    await act(async () => button(`${T}.suggest`)!.click());
  };
  const proposal = (value: TopicsProposal = PROPOSAL): DrafterEvent[] => [
    { type: 'status', step: 'reading' },
    { type: 'proposal', proposal: value },
    { type: 'end' },
  ];

  it('offers the button beside Add topic once there are enough conversations', async () => {
    await render();
    expect(button('agents.form.analytics.addTopic')).toBeTruthy();
    expect(button(`${T}.suggest`)).toBeTruthy();
    expect(mocks.statusCalls).toEqual(['a1']);
    expect(container.textContent).not.toContain(`${T}.hold`);
  });

  it('explains instead while there are too few conversations', async () => {
    mocks.status = { available: false, conversations: 3, needed: 10 };
    await render();
    expect(button(`${T}.suggest`)).toBeUndefined();
    expect(container.textContent).toContain(
      `${T}.hold(count=10,needed=10,formatted=3)`,
    );
  });

  it.each([
    ['the drafter is off', { drafterEnabled: false }, {}],
    ['the caller cannot edit', {}, { disabled: true }],
    ['the agent is not saved', {}, { agentId: '' }],
  ])('stays hidden when %s', async (_name, flags, props) => {
    Object.assign(mocks, flags);
    mocks.status = { available: false, conversations: 3, needed: 10 };
    await render(props);
    expect(button(`${T}.suggest`)).toBeUndefined();
    expect(container.textContent).not.toContain(`${T}.hold`);
    if (!('drafterEnabled' in flags)) expect(mocks.statusCalls).toEqual([]);
  });

  it('runs one topics turn and adds the picked suggestions as new topics', async () => {
    await render();
    await run(proposal());
    expect(mocks.requests).toHaveLength(1);
    expect(mocks.requests[0].recipe).toBe('topics');
    expect(mocks.requests[0].context).toEqual({ agent_id: 'a1' });
    expect(mocks.requests[0].messages).toEqual([
      { role: 'user', content: `${T}.request` },
    ]);

    const text = card()!.textContent!;
    expect(text).toContain(`${T}.read(count=300,formatted=300,days=30)`);
    expect(text).toContain(`${T}.tried(count=100,formatted=100`);
    expect(text).toContain('Most questions are about parcels.');
    expect(text).toContain(
      `${T}.leftOut(items=${T}.leftOutItem(name=Packaging,reason=Your shipping folder covers it.))`,
    );
    expect(suggestion('t1').textContent).toContain(
      'agents.form.analytics.countOf(count=22,max=150)',
    );
    expect(suggestion('t2').textContent).toContain(
      `${T}.similar(name=Billing)`,
    );
    expect(suggestion('t3').textContent).toContain(
      'agents.form.analytics.groups.overlap',
    );
    // Every suggestion starts ticked; untick the refunds one.
    await act(async () =>
      suggestion('t2').querySelector<HTMLButtonElement>('button')!.click(),
    );
    const add = button(`${T}.add`)!;
    expect(add.textContent).toContain('count=2');
    await act(async () => add.click());

    expect(
      latest!.topics.map(({ name, description, overlap }) => ({
        name,
        description,
        overlap,
      })),
    ).toEqual([
      {
        name: 'Delivery delays',
        description: 'Late or stuck parcels.',
        overlap: false,
      },
      { name: 'Bug report', description: 'Errors and crashes.', overlap: true },
    ]);
    expect(
      latest!.topics.every((topic) => /^[a-z0-9]{16}$/.test(topic.id)),
    ).toBe(true);
    expect(card()).toBeNull();
  });

  it('marks an estimated share, not a measured one', async () => {
    await render();
    await run(proposal());
    expect(suggestion('t1').textContent).toContain(`${T}.share(share=31%)`);
    expect(suggestion('t1').textContent).not.toContain(`${T}.estimate`);
    expect(suggestion('t2').textContent).toContain(`${T}.estimate`);
  });

  it('says which folders the picked topics push out', async () => {
    await render({ maxTopics: 3 });
    await run(proposal());
    // 3 slots: shipping and returns are offered; the 2 picked topics that sort
    // questions leave room for one folder, so returns goes.
    const note = card()!.querySelector('[data-note="pushesOut"]')!;
    expect(note.textContent).toBe(`${T}.pushesOut(count=1,names=returns)`);
  });

  it('discards without touching the topics', async () => {
    await render();
    await run(proposal());
    await act(async () => button(`${T}.discard`)!.click());
    expect(card()).toBeNull();
    expect(latest).toBeUndefined();
    expect(button(`${T}.suggest`)).toBeTruthy();
  });

  it('shows a failed turn with Try again, and retries it', async () => {
    await render();
    await run([{ type: 'error', code: 'model_error' }, { type: 'end' }]);
    const alert = card()!.querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain('drafter.errors.model_error.title');
    mocks.scripts.push(proposal());
    await act(async () => button('drafter.retry')!.click());
    expect(mocks.requests).toHaveLength(2);
    expect(card()!.querySelector('[data-suggestion="t1"]')).not.toBeNull();
  });

  it.each(['model_error', 'invalid_output'] as const)(
    "says no topics were added when a turn fails with %s, not the form's copy",
    async (code) => {
      await render();
      await run([{ type: 'error', code }, { type: 'end' }]);
      const alert = card()!.querySelector('[role="alert"]')!;
      expect(alert.textContent).toContain(`drafter.errors.${code}.title`);
      expect(alert.textContent).toContain(`${T}.errors.${code}`);
      expect(alert.textContent).not.toContain(
        `drafter.errors.${code}.description`,
      );
    },
  );

  it('announces the status line, not the whole card', async () => {
    await render();
    await run(proposal());
    expect(card()!.hasAttribute('aria-live')).toBe(false);
    const status = card()!.querySelector('[data-item="status"]')!;
    expect(status.getAttribute('aria-live')).toBe('polite');
  });
});
