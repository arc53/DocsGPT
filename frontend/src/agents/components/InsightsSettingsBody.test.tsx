import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { AnalyticsConfig, AnalyticsTopic } from '../types';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A name the string carries shows as `key(name)`, so titles can be checked.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string'
        ? `${key}(${opts.name})`
        : opts && typeof opts.names === 'string'
          ? `${key}(${opts.names})`
          : opts && opts.max !== undefined && opts.count !== undefined
            ? `${key}(${opts.count}/${opts.max})`
            : key,
  }),
}));

const getTopicFolders = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getTopicFolders: (...args: unknown[]) => getTopicFolders(...args),
  },
}));

import InsightsSettingsBody from './InsightsSettingsBody';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'agents.form.analytics';

// Largest first, as the server lists them.
const FOLDERS = [
  { name: 'integrations', description: 'Pages such as: Slack' },
  { name: 'billing', description: 'Pages such as: Plans' },
  { name: 'data', description: 'Pages such as: Export' },
];

const topic = (
  name: string,
  overlap = false,
  extra: Partial<AnalyticsTopic> = {},
): AnalyticsTopic => ({
  id: `${name.toLowerCase().replace(/[^a-z0-9]/g, '')}00000000`.slice(0, 16),
  name,
  description: '',
  overlap,
  ...extra,
});

const PRICING = topic('Pricing question', true, {
  description: 'The user asks about prices.',
});

let latest: AnalyticsConfig | undefined;

const folders = (list: { name: string; description: string }[]) => ({
  ok: true,
  json: () => Promise.resolve({ success: true, folders: list }),
});

function Harness({
  initial,
  disabled = false,
  agentId = 'a1',
  maxTopics = 15,
  maxOverlapping = 20,
  topicSource,
  active = true,
}: {
  initial?: AnalyticsConfig;
  disabled?: boolean;
  agentId?: string;
  maxTopics?: number;
  maxOverlapping?: number;
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
        maxOverlapping={maxOverlapping}
        disabled={disabled}
        topicSource={topicSource}
        active={active}
        token="token"
      />
    </div>
  );
}

const setInput = (
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

const config = (extra: Partial<AnalyticsConfig> = {}): AnalyticsConfig => ({
  ...DEFAULT_ANALYTICS,
  ...extra,
});

describe('InsightsSettingsBody', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    latest = undefined;
    getTopicFolders.mockReset();
    getTopicFolders.mockResolvedValue(folders(FOLDERS));
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
  const dialog = () => document.body.querySelector('[role="dialog"]');
  const block = () =>
    container.querySelector<HTMLElement>('[data-testid="analytics-topics"]')!;
  const rows = () =>
    Array.from(block().querySelectorAll<HTMLElement>('[data-slot="list-row"]'));
  // A folder row's title holds its name and the From sources badge.
  const rowName = (row: HTMLElement) =>
    (row.querySelector('p span.truncate') ?? row.querySelector('p'))!
      .textContent;
  const names = () => rows().map(rowName);
  const isFolder = (row: HTMLElement) =>
    row.textContent!.includes(`${K}.fromSources`);
  const groupTitles = () =>
    Array.from(block().querySelectorAll('h4')).map((h) => h.textContent);
  const openMenu = async (row: HTMLElement) => {
    const trigger = row.querySelector<HTMLButtonElement>(
      '[aria-haspopup="menu"]',
    )!;
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
  const rowNamed = (name: string) => rows().find((r) => rowName(r) === name)!;
  const fill = async (fields: { name?: string; description?: string }) => {
    const form = dialog()!;
    await act(async () => {
      if (fields.name !== undefined)
        setInput(form.querySelector('input')!, fields.name);
      if (fields.description !== undefined)
        setInput(form.querySelector('textarea')!, fields.description);
    });
  };
  const overlapSwitch = () =>
    document.body.querySelector<HTMLButtonElement>(
      '[data-testid="topic-overlap"]',
    );
  const submit = async (label = `${K}.modal.submitAdd`) => {
    await act(async () => button(label)!.click());
  };
  const notes = () => block().textContent!;

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
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-testid="analytics-enabled"]')!
        .click(),
    );
    expect(latest!.enabled).toBe(false);
    expect(block()).toBeNull();
    expect(
      container.querySelector('[data-testid="analytics-digest"]'),
    ).toBeNull();
  });

  describe('the default list', () => {
    it("lists the agent's folders by name, each marked as from sources, with a count", async () => {
      await render();
      expect(getTopicFolders).toHaveBeenCalledWith('a1', 'token');
      expect(names()).toEqual(['billing', 'data', 'integrations']);
      expect(rows().every(isFolder)).toBe(true);
      expect(block().querySelector('h3')!.textContent).toBe(`${K}.topics3`);
      // One kind only: no group headings.
      expect(groupTitles()).toEqual([]);
    });

    it.each([
      ['off screen', { active: false }],
      ['read-only', { disabled: true }],
      ['unsaved', { agentId: '' }],
      ['a workflow', { topicSource: 'none' as const }],
      ['insights off', { initial: config({ enabled: false }) }],
    ])('loads no folders %s', async (_name, props) => {
      await render(props);
      expect(getTopicFolders).not.toHaveBeenCalled();
    });

    it('shows skeleton rows while the folders load', async () => {
      getTopicFolders.mockReturnValue(new Promise(() => undefined));
      await render();
      expect(block().querySelector('[aria-busy="true"]')).not.toBeNull();
    });
  });

  describe('folders', () => {
    it('hides one from its menu and shows it again from the note', async () => {
      await render();
      await openMenu(rowNamed('data'));
      await act(async () => menuItem(`${K}.hide`).click());
      expect(latest!.hidden_folders).toEqual(['data']);
      expect(names()).toEqual(['billing', 'integrations']);
      expect(notes()).toContain(`${K}.notes.hidden(data)`);
      await act(async () => button(`${K}.notes.show`)!.click());
      expect(latest!.hidden_folders).toEqual([]);
      expect(names()).toEqual(['billing', 'data', 'integrations']);
    });

    it('turns an edited folder into an own topic and hides the folder', async () => {
      await render();
      await openMenu(rowNamed('billing'));
      await act(async () => menuItem(`${K}.edit`).click());
      expect(dialog()!.textContent).toContain(`${K}.modal.editFolder(billing)`);
      expect(dialog()!.querySelector('input')!.value).toBe('billing');
      expect(dialog()!.querySelector('textarea')!.value).toBe(
        'Pages such as: Plans',
      );
      await fill({ description: 'Plans, invoices and refunds.' });
      await submit(`${K}.modal.submitSave`);
      expect(latest!.hidden_folders).toEqual(['billing']);
      expect(latest!.topics).toEqual([
        expect.objectContaining({
          name: 'billing',
          description: 'Plans, invoices and refunds.',
          overlap: false,
        }),
      ]);
      const billing = rowNamed('billing');
      expect(isFolder(billing)).toBe(false);
      // Replaced, not hidden: nothing offers the folder back while the topic is there.
      expect(notes()).not.toContain(`${K}.notes.hidden`);
      await openMenu(rowNamed('billing'));
      await act(async () => menuItem(`${K}.remove`).click());
      expect(notes()).toContain(`${K}.notes.hidden(billing)`);
    });

    it('pre-fills a folder name past the topic limit cut to fit', async () => {
      const long =
        'q3-2025 vendor due diligence questionnaire - halvorsen logistics (final, signed).pdf';
      getTopicFolders.mockResolvedValue(
        folders([{ name: long, description: 'Pages such as: Q' }, ...FOLDERS]),
      );
      await render();
      await openMenu(rowNamed(long));
      await act(async () => menuItem(`${K}.edit`).click());
      const value = dialog()!.querySelector('input')!.value;
      expect(value).toBe(long.slice(0, 60));
      await submit(`${K}.modal.submitSave`);
      expect(latest!.topics).toEqual([
        expect.objectContaining({ name: long.slice(0, 60).trim() }),
      ]);
    });

    it('cuts the smallest folders past the limit, own topics first', async () => {
      await render({
        maxTopics: 3,
        initial: config({ topics: [topic('Auth')] }),
      });
      expect(names()).toEqual(['Auth', 'billing', 'integrations']);
      expect(notes()).toContain(`${K}.notes.cut(data)`);
    });

    it('offers a retry when they fail to load, keeping own topics', async () => {
      getTopicFolders.mockRejectedValueOnce(new Error('down'));
      await render({ initial: config({ topics: [topic('Auth')] }) });
      expect(names()).toEqual(['Auth']);
      expect(notes()).toContain(`${K}.notes.foldersFailed`);
      await act(async () => button('retry')!.click());
      expect(getTopicFolders).toHaveBeenCalledTimes(2);
      expect(names()).toEqual(['Auth', 'billing', 'data', 'integrations']);
    });
  });

  describe('adding and editing', () => {
    it('adds a topic that sorts questions by default, with a new id', async () => {
      await render();
      await act(async () => button(`${K}.addTopic`)!.click());
      expect(overlapSwitch()!.getAttribute('aria-checked')).toBe('false');
      expect(dialog()!.textContent).toContain(`${K}.modal.reachOnePick`);
      await fill({ name: '  Auth ', description: '' });
      await submit();
      expect(latest!.topics).toEqual([
        {
          id: expect.stringMatching(/^[a-z0-9]{16}$/),
          name: 'Auth',
          description: '',
          overlap: false,
        },
      ]);
      expect(names()).toEqual(['Auth', 'billing', 'data', 'integrations']);
    });

    it('checks the name against own topics, shown folders and the reserved one', async () => {
      await render({ initial: config({ topics: [PRICING] }) });
      await act(async () => button(`${K}.addTopic`)!.click());
      await submit();
      expect(dialog()!.textContent).toContain(`${K}.errors.nameRequired`);
      for (const [name, error] of [
        ['pricing QUESTION', 'topicNameTaken'],
        ['Billing', 'topicNameTaken'],
        ['None of these', 'topicNameReserved'],
      ]) {
        await fill({ name });
        expect(dialog()!.textContent).toContain(`${K}.errors.${error}`);
      }
      expect(latest).toBeUndefined();
    });

    it('splits the list into two groups once a topic can overlap', async () => {
      await render();
      await act(async () => button(`${K}.addTopic`)!.click());
      await fill({ name: 'Bug report' });
      await act(async () => overlapSwitch()!.click());
      expect(dialog()!.textContent).toContain(`${K}.modal.reachOverlap`);
      await submit();
      expect(latest!.topics).toEqual([
        expect.objectContaining({ name: 'Bug report', overlap: true }),
      ]);
      expect(groupTitles()).toEqual([
        `${K}.groups.onePick`,
        `${K}.groups.overlap`,
      ]);
      expect(names()).toEqual([
        'billing',
        'data',
        'integrations',
        'Bug report',
      ]);
    });

    it('fits the description to the kind: 150 units, or 300 when it can overlap', async () => {
      await render();
      await act(async () => button(`${K}.addTopic`)!.click());
      await fill({ name: 'Long', description: 'x'.repeat(200) });
      await submit();
      expect(dialog()!.textContent).toContain(
        `${K}.errors.topicDescriptionTooLong`,
      );
      await act(async () => overlapSwitch()!.click());
      expect(dialog()!.textContent).not.toContain(
        `${K}.errors.topicDescriptionTooLong`,
      );
      await submit();
      expect(latest!.topics[0].description).toHaveLength(200);
    });

    it('keeps the id on an edit and warns when the kind changes', async () => {
      await render({ initial: config({ topics: [PRICING] }) });
      await openMenu(rowNamed('Pricing question'));
      await act(async () => menuItem(`${K}.edit`).click());
      expect(dialog()!.querySelector('[role="note"]')).toBeNull();
      await act(async () => overlapSwitch()!.click());
      expect(dialog()!.querySelector('[role="note"]')!.textContent).toBe(
        `${K}.modal.kindChangeToOnePick`,
      );
      await fill({ name: 'Pricing' });
      await submit(`${K}.modal.submitSave`);
      expect(latest!.topics).toEqual([
        { ...PRICING, name: 'Pricing', overlap: false },
      ]);
    });

    it('refuses a name past the limit', async () => {
      await render();
      await act(async () => button(`${K}.addTopic`)!.click());
      await fill({ name: 'n'.repeat(61) });
      await submit();
      expect(dialog()!.textContent).toContain(`${K}.errors.topicNameTooLong`);
      expect(latest).toBeUndefined();
      await fill({ name: 'n'.repeat(60) });
      expect(dialog()!.textContent).not.toContain(
        `${K}.errors.topicNameTooLong`,
      );
      await submit();
      expect(latest!.topics[0].name).toHaveLength(60);
    });

    it('takes 60 characters outside the BMP, as the server counts them', async () => {
      // `maxlength` counts UTF-16 units, so it would stop 60 emoji at 30;
      // the limit is checked in code points instead.
      await render();
      await act(async () => button(`${K}.addTopic`)!.click());
      expect(dialog()!.querySelector('input')!.hasAttribute('maxlength')).toBe(
        false,
      );
      await fill({ name: '📦'.repeat(60) });
      await submit();
      expect(Array.from(latest!.topics[0].name)).toHaveLength(60);
    });

    it('has no overlap switch when the server allows none', async () => {
      await render({ maxOverlapping: 0 });
      await act(async () => button(`${K}.addTopic`)!.click());
      expect(overlapSwitch()).toBeNull();
    });

    it("locks the switch on once topics that don't overlap are full", async () => {
      await render({
        maxTopics: 2,
        initial: config({ topics: [topic('A'), topic('B')] }),
      });
      await act(async () => button(`${K}.addTopic`)!.click());
      expect(overlapSwitch()!.getAttribute('aria-checked')).toBe('true');
      expect(overlapSwitch()!.disabled).toBe(true);
      expect(dialog()!.textContent).toContain(`${K}.modal.onePickFull`);
    });

    it('drops Add topic once both kinds are full and says so', async () => {
      await render({
        maxTopics: 2,
        maxOverlapping: 1,
        initial: config({ topics: [topic('A'), topic('B'), PRICING] }),
      });
      expect(button(`${K}.addTopic`)).toBeUndefined();
      expect(notes()).toContain(`${K}.notes.full`);
    });
  });

  describe('past a lowered limit', () => {
    const overlapping = [1, 2, 3, 4, 5].map((n) => topic(`Tag ${n}`, true));

    it('says when a kind has more topics than the server now allows', async () => {
      await render({
        maxTopics: 2,
        maxOverlapping: 3,
        initial: config({
          topics: [topic('A'), topic('B'), topic('C'), ...overlapping],
        }),
      });
      expect(notes()).toContain(`${K}.notes.overOnePick`);
      expect(notes()).toContain(`${K}.notes.overOverlapping`);
      expect(notes()).not.toContain(`${K}.notes.full`);
      expect(button(`${K}.addTopic`)).toBeUndefined();
    });

    it('says nothing at the limit', async () => {
      await render({
        maxOverlapping: 5,
        initial: config({ topics: overlapping }),
      });
      expect(notes()).not.toContain(`${K}.notes.overOverlapping`);
    });

    it('lets an overlapping topic be switched off once the server allows none', async () => {
      await render({
        maxOverlapping: 0,
        initial: config({ topics: [PRICING] }),
      });
      expect(notes()).toContain(`${K}.notes.overlapOff`);
      await openMenu(rowNamed('Pricing question'));
      await act(async () => menuItem(`${K}.edit`).click());
      expect(overlapSwitch()!.disabled).toBe(false);
      await act(async () => overlapSwitch()!.click());
      // Off, it can't go back on: the server takes none.
      expect(overlapSwitch()!.disabled).toBe(true);
      await submit(`${K}.modal.submitSave`);
      expect(latest!.topics).toEqual([{ ...PRICING, overlap: false }]);
      expect(notes()).not.toContain(`${K}.notes.overlapOff`);
    });
  });

  describe('removing', () => {
    it('removes a topic that sorts questions at once', async () => {
      await render({ initial: config({ topics: [topic('Auth')] }) });
      await openMenu(rowNamed('Auth'));
      await act(async () => menuItem(`${K}.remove`).click());
      expect(latest!.topics).toEqual([]);
    });

    it('asks first for one that can overlap, since its results go with it', async () => {
      await render({ initial: config({ topics: [PRICING] }) });
      await openMenu(rowNamed('Pricing question'));
      await act(async () => menuItem(`${K}.remove`).click());
      expect(latest).toBeUndefined();
      expect(document.body.textContent).toContain(
        `${K}.removeTopic.title(Pricing question)`,
      );
      await act(async () => button(`${K}.removeTopic.submit`)!.click());
      expect(latest!.topics).toEqual([]);
    });
  });

  describe('empty and edge states', () => {
    const empty = () => block().textContent!;

    it('asks a workflow for its own topics', async () => {
      await render({ topicSource: 'none' });
      expect(rows()).toEqual([]);
      expect(empty()).toContain(`${K}.empty.title`);
      expect(empty()).toContain(`${K}.empty.workflow`);
    });

    it('says folders come after the first save', async () => {
      await render({ agentId: '' });
      expect(empty()).toContain(`${K}.empty.unsaved`);
    });

    it('notes it under own topics on an unsaved agent', async () => {
      await render({
        agentId: '',
        initial: config({ topics: [topic('Auth'), topic('Billing')] }),
      });
      expect(notes()).toContain(`${K}.notes.unsaved`);
    });

    it('says when the sources have no folders', async () => {
      getTopicFolders.mockResolvedValue(folders([]));
      await render();
      expect(empty()).toContain(`${K}.empty.noFolders`);
    });

    it('offers every hidden folder back when nothing else is left', async () => {
      await render({
        initial: config({
          hidden_folders: ['billing', 'data', 'integrations'],
        }),
      });
      expect(empty()).toContain(`${K}.empty.allHidden`);
      await act(async () => button(`${K}.empty.showFolders`)!.click());
      expect(latest!.hidden_folders).toEqual([]);
    });

    it('says one topic on its own sorts nothing', async () => {
      getTopicFolders.mockResolvedValue(folders([FOLDERS[0]]));
      await render();
      expect(names()).toEqual(['integrations']);
      expect(notes()).toContain(`${K}.notes.single`);
    });

    it("is read-only for a caller who can't save, without listing folders", async () => {
      await render({
        disabled: true,
        initial: config({ topics: [PRICING, topic('Auth')] }),
      });
      expect(button(`${K}.addTopic`)).toBeUndefined();
      expect(block().querySelector('[aria-haspopup="menu"]')).toBeNull();
      expect(names()).toEqual(['Auth', 'Pricing question']);
      expect(notes()).toContain(`${K}.notes.unlisted`);
    });
  });
});
