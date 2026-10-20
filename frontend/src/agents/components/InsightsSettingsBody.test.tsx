import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { AnalyticsConfig } from '../types';

const dispatch = vi.fn();
vi.mock('react-redux', () => ({ useDispatch: () => dispatch }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A name the string carries shows as `key(name)`, so titles can be checked.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string'
        ? `${key}(${opts.name})`
        : opts && opts.max !== undefined && opts.count !== undefined
          ? `${key}(${opts.count}/${opts.max})`
          : key,
  }),
}));

const getTopicSuggestions = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getTopicSuggestions: (...args: unknown[]) => getTopicSuggestions(...args),
  },
}));

import InsightsSettingsBody from './InsightsSettingsBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'agents.form.analytics';

const TAG = {
  id: 'a1b2c3d4e5f60718',
  name: 'Pricing question',
  description: 'The user asks about prices.',
};

const FOLDERS = [
  { name: 'billing', description: 'Pages such as: Plans' },
  { name: 'data', description: 'Pages such as: Export' },
  { name: 'integrations', description: 'Pages such as: Slack' },
];

let latest: AnalyticsConfig | undefined;

const suggestions = (topics: { name: string; description: string }[]) => ({
  ok: true,
  json: () => Promise.resolve({ success: true, topics }),
});

function Harness({
  initial,
  disabled = false,
  agentId = 'a1',
  maxTopics = 3,
  maxTags = 20,
  topicSource,
  active = true,
}: {
  initial?: AnalyticsConfig;
  disabled?: boolean;
  agentId?: string;
  maxTopics?: number;
  maxTags?: number;
  topicSource?: 'sources' | 'none';
  active?: boolean;
}) {
  const [value, setValue] = useState<AnalyticsConfig | undefined>(initial);
  return (
    <div className="flex flex-col gap-5">
      <InsightsSettingsBody
        value={value}
        onChange={(next) => {
          latest = next;
          setValue(next);
        }}
        agentId={agentId}
        maxTopics={maxTopics}
        maxTags={maxTags}
        disabled={disabled}
        topicSource={topicSource}
        active={active}
        token="token"
      />
    </div>
  );
}

const setValue = (
  element: HTMLInputElement | HTMLTextAreaElement,
  text: string,
) => {
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, text);
  element.dispatchEvent(new Event('input', { bubbles: true }));
};

describe('InsightsSettingsBody', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    latest = undefined;
    dispatch.mockReset();
    getTopicSuggestions.mockReset();
    getTopicSuggestions.mockResolvedValue(suggestions(FOLDERS));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (props: React.ComponentProps<typeof Harness> = {}) => {
    await act(async () => root.render(<Harness {...props} />));
  };

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((el) => el.textContent === text);
  const dialog = () => document.body.querySelector('[role="dialog"]')!;
  const topicsBlock = () =>
    container.querySelector<HTMLElement>('[data-testid="analytics-topics"]')!;
  const tagsBlock = () =>
    container.querySelector<HTMLElement>('[data-testid="analytics-tags"]')!;
  const groupSwitch = () =>
    container.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-group-topics"]',
    )!;
  const rowTitles = (block: HTMLElement) =>
    Array.from(block.querySelectorAll('[data-slot="list-row"]')).map(
      (row) => row.querySelector('p')!.textContent,
    );
  const openMenu = async (block: HTMLElement, index: number) => {
    const trigger = block.querySelectorAll<HTMLButtonElement>(
      '[aria-haspopup="menu"]',
    )[index];
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  };
  const menuItem = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === text)!;

  it('links Learn more to the agent settings heading of the docs', async () => {
    await render({ initial: DEFAULT_ANALYTICS });
    const link = container.querySelector<HTMLAnchorElement>(
      'a[href*="analytics-and-logs"]',
    );
    expect(link?.getAttribute('href')).toBe(
      'https://docs.docsgpt.cloud/Using/analytics-and-logs#analytics-settings-for-an-agent',
    );
  });

  it('hides the rest when Collect insights is off', async () => {
    await render();
    const enabled = container.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-enabled"]',
    )!;
    await act(async () => enabled.click());
    expect(latest!.enabled).toBe(false);
    expect(topicsBlock()).toBeNull();
    expect(tagsBlock()).toBeNull();
    expect(
      container.querySelector('[data-testid="analytics-digest"]'),
    ).toBeNull();
  });

  it('hides Tags when the server allows none', async () => {
    await render({ maxTags: 0 });
    expect(tagsBlock()).toBeNull();
  });

  // IN-6 B: Topics and Tags are peer SectionHeaders, each with its one-line
  // description, and no three-way toggle.
  it('draws Topics and Tags as peer sub-headings with descriptions', async () => {
    await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
    const topicsHeader = topicsBlock().querySelector(
      '[data-slot="section-header"]',
    )!;
    expect(topicsHeader.querySelector('h3')!.textContent).toBe(`${K}.topics`);
    expect(topicsHeader.textContent).toContain(`${K}.topicsDescription`);
    const tagsHeader = tagsBlock().querySelector(
      '[data-slot="section-header"]',
    )!;
    expect(tagsHeader.querySelector('h3')!.textContent).toContain(`${K}.tags`);
    expect(tagsHeader.textContent).toContain(`${K}.tagsDescription`);
    expect(tagsHeader.textContent).toContain(`${K}.addTag`);
    expect(container.querySelector('[role="radiogroup"]')).toBeNull();
    expect(container.textContent).not.toContain('topicModes');
  });

  it('puts the sub-headings one level down when asked (a workflow card)', async () => {
    await act(async () =>
      root.render(
        <InsightsSettingsBody
          value={DEFAULT_ANALYTICS}
          onChange={() => undefined}
          agentId="a1"
          maxTopics={3}
          maxTags={20}
          headingLevel="h4"
          token="token"
        />,
      ),
    );
    expect(topicsBlock().querySelector('h4')!.textContent).toBe(`${K}.topics`);
    expect(container.querySelector('h3')).toBeNull();
  });

  // DESIGN › Counts: a plain number, with the limit only at the cap.
  it('counts tags as a plain number and names the limit only at the cap', async () => {
    await render({
      initial: { ...DEFAULT_ANALYTICS, tags: [TAG] },
      maxTags: 2,
    });
    const count = () =>
      tagsBlock().querySelector('[data-slot="count"]')!.textContent;
    expect(count()).toBe('1');
    await act(async () => button(`${K}.addTag`)!.click());
    const [name] = Array.from(dialog().querySelectorAll('input'));
    await act(async () => {
      setValue(name, 'Wants a refund');
      setValue(
        dialog().querySelector('textarea')!,
        'The user asks for their money back.',
      );
    });
    await act(async () => button(`${K}.modal.submitAdd`)!.click());
    expect(count()).toBe(`${K}.countOf(2/2)`);
    expect(button(`${K}.addTag`)).toBeUndefined();
  });

  describe('topics from sources', () => {
    it('shows the folders as read-only rows with their pages', async () => {
      await render();
      expect(getTopicSuggestions).toHaveBeenCalledWith('a1', 'token');
      expect(groupSwitch().getAttribute('aria-checked')).toBe('true');
      expect(topicsBlock().textContent).toContain(`${K}.topicHints.auto`);
      expect(rowTitles(topicsBlock())).toEqual([
        'billing',
        'data',
        'integrations',
      ]);
      expect(topicsBlock().textContent).toContain('Pages such as: Plans');
      expect(topicsBlock().querySelector('[aria-haspopup="menu"]')).toBeNull();
      expect(button(`${K}.customize`)).toBeDefined();
      expect(button(`${K}.addTopic`)).toBeUndefined();
      // No count on the folders: nothing to fill.
      expect(topicsBlock().querySelector('[data-slot="count"]')).toBeNull();
    });

    // FX-3: the folders load only while the body is on screen.
    it('fetches the folders only while active', async () => {
      await render({ active: false });
      expect(getTopicSuggestions).not.toHaveBeenCalled();
      await render({ active: true });
      expect(getTopicSuggestions).toHaveBeenCalledTimes(1);
      // Closing and reopening reuses what came back.
      await render({ active: false });
      await render({ active: true });
      expect(getTopicSuggestions).toHaveBeenCalledTimes(1);
    });

    it('asks for no folders before the agent is saved, or for a read-only role', async () => {
      await render({ agentId: '' });
      await render({ agentId: 'a1', disabled: true });
      expect(getTopicSuggestions).not.toHaveBeenCalled();
    });

    it('says when the sources give too few folders to group by', async () => {
      getTopicSuggestions.mockResolvedValue(suggestions([FOLDERS[0]]));
      await render();
      const empty = topicsBlock().querySelector('[data-slot="empty-state"]')!;
      expect(empty.textContent).toBe(`${K}.autoTopicsNone`);
      expect(empty.getAttribute('data-size')).toBe('sm');
      expect(topicsBlock().querySelector('[data-slot="list-row"]')).toBeNull();
    });

    it('turns grouping off and back on, keeping a custom list for later', async () => {
      const items = [{ name: 'Installation', description: 'Docker' }];
      await render({
        initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'custom', items } },
      });
      await act(async () => groupSwitch().click());
      expect(latest!.topics).toEqual({ mode: 'off', items });
      expect(topicsBlock().textContent).toContain(`${K}.topicHints.off`);
      expect(topicsBlock().querySelector('[data-slot="list-row"]')).toBeNull();
      expect(button(`${K}.customize`)).toBeUndefined();
      await act(async () => groupSwitch().click());
      expect(latest!.topics).toEqual({ mode: 'custom', items });
      expect(rowTitles(topicsBlock())).toEqual(['Installation']);
    });

    it('turns back on to From sources when there is no list of its own', async () => {
      await render({
        initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'off', items: [] } },
      });
      expect(groupSwitch().getAttribute('aria-checked')).toBe('false');
      await act(async () => groupSwitch().click());
      expect(latest!.topics).toEqual({ mode: 'auto', items: [] });
    });

    it('Customize copies the folders into an editable list', async () => {
      await render({ maxTopics: 15 });
      await act(async () => button(`${K}.customize`)!.click());
      expect(latest!.topics).toEqual({ mode: 'custom', items: FOLDERS });
      expect(topicsBlock().textContent).toContain(`${K}.topicHints.custom`);
      expect(rowTitles(topicsBlock())).toEqual([
        'billing',
        'data',
        'integrations',
      ]);
      expect(
        topicsBlock().querySelectorAll('[aria-haspopup="menu"]'),
      ).toHaveLength(3);
      expect(button(`${K}.addTopic`)).toBeDefined();
      expect(button(`${K}.resetToSources`)).toBeDefined();
      expect(button(`${K}.customize`)).toBeUndefined();
      expect(
        topicsBlock().querySelector('[data-slot="count"]')!.textContent,
      ).toBe('3');
    });

    it('Customize keeps to the topic limit', async () => {
      await render({ maxTopics: 2 });
      await act(async () => button(`${K}.customize`)!.click());
      expect(latest!.topics.items.map((item) => item.name)).toEqual([
        'billing',
        'data',
      ]);
      expect(
        topicsBlock().querySelector('[data-slot="count"]')!.textContent,
      ).toBe(`${K}.countOf(2/2)`);
      expect(button(`${K}.addTopic`)).toBeUndefined();
    });

    it('Customize toasts when the folders cannot load', async () => {
      getTopicSuggestions.mockResolvedValue({ ok: false });
      await render();
      await act(async () => button(`${K}.customize`)!.click());
      expect(latest).toBeUndefined();
      expect(dispatch).toHaveBeenCalledWith(
        expect.objectContaining({
          payload: {
            variant: 'destructive',
            message: `${K}.suggestFailed`,
          },
        }),
      );
    });

    it('Customize starts an empty list for an agent not saved yet', async () => {
      await render({ agentId: '' });
      await act(async () => button(`${K}.customize`)!.click());
      expect(latest!.topics).toEqual({ mode: 'custom', items: [] });
      const empty = topicsBlock().querySelector('[data-slot="empty-state"]')!;
      expect(empty.textContent).toBe(`${K}.topicsEmpty`);
      expect(empty.getAttribute('data-size')).toBe('sm');
    });

    it('Reset to sources goes straight back while the list is the folders', async () => {
      await render({ maxTopics: 15 });
      await act(async () => button(`${K}.customize`)!.click());
      await act(async () => button(`${K}.resetToSources`)!.click());
      expect(document.body.querySelector('[role="dialog"]')).toBeNull();
      expect(latest!.topics).toEqual({ mode: 'auto', items: [] });
      expect(button(`${K}.customize`)).toBeDefined();
    });

    it('Reset to sources confirms once the list differs from the folders', async () => {
      await render({ maxTopics: 15 });
      await act(async () => button(`${K}.customize`)!.click());
      await openMenu(topicsBlock(), 0);
      await act(async () => menuItem(`${K}.remove`).click());
      expect(latest!.topics.items.map((item) => item.name)).toEqual([
        'data',
        'integrations',
      ]);
      await act(async () => button(`${K}.resetToSources`)!.click());
      expect(dialog().textContent).toContain(`${K}.resetTopics.title`);
      expect(latest!.topics.mode).toBe('custom');
      await act(async () => button(`${K}.resetTopics.submit`)!.click());
      expect(latest!.topics).toEqual({ mode: 'auto', items: [] });
    });
  });

  describe('a workflow (no sources of its own)', () => {
    it('reads a stored From sources as off and offers no folders', async () => {
      await render({ topicSource: 'none' });
      expect(getTopicSuggestions).not.toHaveBeenCalled();
      expect(groupSwitch().getAttribute('aria-checked')).toBe('false');
      expect(topicsBlock().textContent).toContain(
        `${K}.topicHints.workflowOff`,
      );
      expect(button(`${K}.customize`)).toBeUndefined();
      expect(button(`${K}.addTopic`)).toBeUndefined();
    });

    it('turns on to its own list, with Add topic and no Reset', async () => {
      await render({ topicSource: 'none' });
      await act(async () => groupSwitch().click());
      expect(latest!.topics).toEqual({ mode: 'custom', items: [] });
      expect(button(`${K}.addTopic`)).toBeDefined();
      expect(button(`${K}.resetToSources`)).toBeUndefined();
      await act(async () => groupSwitch().click());
      expect(latest!.topics.mode).toBe('off');
    });
  });

  describe('tags', () => {
    it('checks a new tag before adding it, and gives it an id', async () => {
      await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
      await act(async () => button(`${K}.addTag`)!.click());
      const [name] = Array.from(dialog().querySelectorAll('input'));
      const description = dialog().querySelector('textarea')!;
      const submit = button(`${K}.modal.submitAdd`)!;
      await act(async () => submit.click());
      expect(dialog().textContent).toContain(`${K}.errors.nameRequired`);
      expect(dialog().textContent).toContain(`${K}.errors.descriptionRequired`);
      await act(async () => setValue(name, ' pricing QUESTION '));
      expect(dialog().textContent).toContain(`${K}.errors.tagNameTaken`);
      await act(async () => {
        setValue(name, 'Wants a refund');
        setValue(description, 'The user asks for their money back.');
      });
      await act(async () => submit.click());
      expect(latest!.tags).toHaveLength(2);
      expect(latest!.tags[1]).toMatchObject({
        name: 'Wants a refund',
        description: 'The user asks for their money back.',
      });
      expect(latest!.tags[1].id).toMatch(/^[a-z0-9]{8,32}$/);
      expect(latest!.tags[1].id).not.toBe(TAG.id);
    });

    it('keeps a tag id when it is renamed, and saves with Save', async () => {
      await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
      await openMenu(tagsBlock(), 0);
      await act(async () => menuItem(`${K}.edit`).click());
      expect(dialog().textContent).toContain(`${K}.modal.editTag`);
      const name = dialog().querySelector('input')!;
      expect(name.value).toBe('Pricing question');
      await act(async () => setValue(name, 'Pricing'));
      expect(button(`${K}.modal.submitAdd`)).toBeUndefined();
      await act(async () => button(`${K}.modal.submitSave`)!.click());
      expect(latest!.tags).toEqual([{ ...TAG, name: 'Pricing' }]);
    });

    it('gives the row menu Pencil and Trash icons', async () => {
      await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
      await openMenu(tagsBlock(), 0);
      expect(
        menuItem(`${K}.edit`).querySelector('svg.lucide-pencil'),
      ).not.toBeNull();
      expect(
        menuItem(`${K}.remove`).querySelector('svg.lucide-trash-2'),
      ).not.toBeNull();
    });

    it('confirms before removing a tag, since its history goes', async () => {
      await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
      await openMenu(tagsBlock(), 0);
      await act(async () => menuItem(`${K}.remove`).click());
      expect(dialog().textContent).toContain(
        `${K}.removeTag.title(Pricing question)`,
      );
      expect(latest).toBeUndefined();
      await act(async () => button(`${K}.removeTag.submit`)!.click());
      expect(latest!.tags).toEqual([]);
    });

    it('shows an empty list as a small EmptyState', async () => {
      await render();
      const empty = tagsBlock().querySelector('[data-slot="empty-state"]')!;
      expect(empty.textContent).toBe(`${K}.tagsEmpty`);
      expect(empty.getAttribute('data-size')).toBe('sm');
      expect(tagsBlock().querySelector('[data-slot="count"]')).toBeNull();
    });
  });

  describe('custom topics', () => {
    const custom = (
      items = [
        { name: 'Installation', description: 'Pages such as: Docker' },
        { name: 'Billing', description: 'Pages such as: Plans' },
      ],
    ): AnalyticsConfig => ({
      ...DEFAULT_ANALYTICS,
      topics: { mode: 'custom', items },
    });

    it('removes a topic at once (re-adding the name restores it)', async () => {
      await render({ initial: custom() });
      await openMenu(topicsBlock(), 0);
      await act(async () => menuItem(`${K}.remove`).click());
      expect(
        document.body.querySelector('[role="alertdialog"], [role="dialog"]'),
      ).toBeNull();
      expect(latest!.topics.items.map((item) => item.name)).toEqual([
        'Billing',
      ]);
    });

    // FX-14: no translated prefill (the model reads the English form), the
    // description is optional as on the server, and the counter shows only
    // past 80% of the budget.
    it('adds a topic with an empty description and no prefill', async () => {
      await render({ initial: custom([]) });
      await act(async () => button(`${K}.addTopic`)!.click());
      const description = dialog().querySelector('textarea')!;
      expect(description.value).toBe('');
      expect(description.getAttribute('placeholder')).toBe(
        `${K}.modal.topicDescriptionPlaceholder`,
      );
      await act(async () => setValue(dialog().querySelector('input')!, 'Auth'));
      await act(async () => button(`${K}.modal.submitAdd`)!.click());
      expect(latest!.topics.items).toEqual([{ name: 'Auth', description: '' }]);
    });

    it('shows the description counter only past 80% of the budget', async () => {
      await render({ initial: custom([]) });
      await act(async () => button(`${K}.addTopic`)!.click());
      const description = dialog().querySelector('textarea')!;
      await act(async () => setValue(description, 'a'.repeat(120)));
      expect(dialog().textContent).toContain(`${K}.modal.topicDescriptionHint`);
      expect(dialog().textContent).not.toContain(`${K}.countOf`);
      await act(async () => setValue(description, 'a'.repeat(121)));
      expect(dialog().textContent).toContain(`${K}.countOf(121/150)`);
    });

    it('rejects a topic description over the unit budget, counting CJK three times', async () => {
      await render({ initial: custom([]) });
      await act(async () => button(`${K}.addTopic`)!.click());
      const name = dialog().querySelector('input')!;
      const description = dialog().querySelector('textarea')!;
      await act(async () => {
        setValue(name, '安装');
        setValue(description, '页'.repeat(51));
      });
      await act(async () => button(`${K}.modal.submitAdd`)!.click());
      expect(dialog().textContent).toContain(
        `${K}.errors.topicDescriptionTooLong`,
      );
      await act(async () => setValue(description, '页'.repeat(50)));
      await act(async () => button(`${K}.modal.submitAdd`)!.click());
      expect(latest!.topics.items).toEqual([
        { name: '安装', description: '页'.repeat(50) },
      ]);
    });
  });

  it('shows a read-only role the settings, with no actions', async () => {
    await render({
      disabled: true,
      initial: {
        ...DEFAULT_ANALYTICS,
        topics: {
          mode: 'custom',
          items: [{ name: 'Installation', description: 'Pages' }],
        },
        tags: [TAG],
      },
    });
    expect(
      container.querySelector<HTMLButtonElement>(
        '[data-testid="analytics-enabled"]',
      )!.disabled,
    ).toBe(true);
    expect(groupSwitch().disabled).toBe(true);
    expect(button(`${K}.addTag`)).toBeUndefined();
    expect(button(`${K}.addTopic`)).toBeUndefined();
    expect(button(`${K}.resetToSources`)).toBeUndefined();
    expect(container.querySelector('[aria-haspopup="menu"]')).toBeNull();
    expect(container.textContent).toContain('Pricing question');
    expect(container.textContent).toContain('Installation');
  });
});
