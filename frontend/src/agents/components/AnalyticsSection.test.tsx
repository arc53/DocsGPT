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

import AnalyticsSection from './AnalyticsSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TAG = {
  id: 'a1b2c3d4e5f60718',
  name: 'Pricing question',
  description: 'The user asks about prices.',
};

let latest: AnalyticsConfig | undefined;

const suggestions = (names: string[]) => ({
  ok: true,
  json: () =>
    Promise.resolve({
      success: true,
      topics: names.map((name) => ({ name, description: '' })),
    }),
});

function Harness({
  initial,
  available = true,
  disabled = false,
  agentId = 'a1',
}: {
  initial?: AnalyticsConfig;
  available?: boolean;
  disabled?: boolean;
  agentId?: string;
}) {
  const [value, setValue] = useState<AnalyticsConfig | undefined>(initial);
  return (
    <AnalyticsSection
      value={value}
      onChange={(next) => {
        latest = next;
        setValue(next);
      }}
      agentId={agentId}
      available={available}
      maxTopics={3}
      maxTags={20}
      disabled={disabled}
      token="token"
    />
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

describe('AnalyticsSection', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    latest = undefined;
    dispatch.mockReset();
    getTopicSuggestions.mockReset();
    getTopicSuggestions.mockResolvedValue(suggestions([]));
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
    const toggle = container.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-toggle"]',
    );
    if (toggle) await act(async () => toggle.click());
  };

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((el) => el.textContent === text);
  const modeItem = (mode: string) =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-testid="analytics-topic-mode"] button',
      ),
    ).find(
      (item) => item.textContent === `agents.form.analytics.topicModes.${mode}`,
    )!;
  const dialog = () => document.body.querySelector('[role="dialog"]')!;
  const openMenu = async (index: number) => {
    const trigger = container.querySelectorAll<HTMLButtonElement>(
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

  it('is hidden while the server has labelling off and the agent has nothing set', async () => {
    await render({ available: false });
    expect(
      container.querySelector('[data-testid="analytics-section"]'),
    ).toBeNull();
  });

  it('stays, with a note and no On badge, for an agent with settings of its own', async () => {
    await render({
      available: false,
      initial: { ...DEFAULT_ANALYTICS, tags: [TAG] },
    });
    const section = container.querySelector(
      '[data-testid="analytics-section"]',
    )!;
    expect(section.querySelector('[role="note"]')!.textContent).toBe(
      'agents.form.analytics.serverOff',
    );
    expect(
      section.querySelector('[data-testid="analytics-on-badge"]'),
    ).toBeNull();
  });

  it('shows On while labelling, and hides the rest when switched off', async () => {
    await render();
    expect(
      container.querySelector('[data-testid="analytics-on-badge"]'),
    ).not.toBeNull();
    const enabled = container.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-enabled"]',
    )!;
    await act(async () => enabled.click());
    expect(latest!.enabled).toBe(false);
    expect(
      container.querySelector('[data-testid="analytics-tags"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-testid="analytics-on-badge"]'),
    ).toBeNull();
  });

  it('keeps the custom list while another topic mode is on', async () => {
    const items = [
      { name: 'Installation', description: 'Pages such as: Docker' },
    ];
    await render({
      initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'custom', items } },
    });
    expect(
      container.querySelector('[data-testid="analytics-topics"]'),
    ).not.toBeNull();
    // One custom topic is enough: the server asks it beside "none of these".
    expect(container.textContent).not.toContain('topicsFew');
    await act(async () => modeItem('off').click());
    expect(latest!.topics).toEqual({ mode: 'off', items });
    expect(
      container.querySelector('[data-testid="analytics-topics"]'),
    ).toBeNull();
    expect(container.textContent).toContain(
      'agents.form.analytics.topicHints.off',
    );
    await act(async () => modeItem('custom').click());
    expect(container.textContent).toContain('Installation');
  });

  it('appends suggested topics that are not listed, up to the limit', async () => {
    getTopicSuggestions.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          topics: [
            { name: 'installation', description: 'Other text' },
            { name: 'Billing', description: 'Pages such as: Plans' },
            { name: 'Auth', description: 'Pages such as: SSO' },
          ],
        }),
    });
    await render({
      initial: {
        ...DEFAULT_ANALYTICS,
        topics: {
          mode: 'custom',
          items: [
            { name: 'Installation', description: 'Pages such as: Docker' },
          ],
        },
      },
    });
    await act(async () => button('agents.form.analytics.suggest')!.click());
    expect(getTopicSuggestions).toHaveBeenCalledWith('a1', 'token');
    expect(latest!.topics.items.map((item) => item.name)).toEqual([
      'Installation',
      'Billing',
      'Auth',
    ]);
    // The list is now full (3 of 3): no Add or Suggest any more.
    expect(button('agents.form.analytics.addTopic')).toBeUndefined();
    expect(button('agents.form.analytics.suggest')).toBeUndefined();
    expect(container.querySelector('[data-slot="count"]')!.textContent).toBe(
      'agents.form.analytics.countOf(3/3)',
    );
  });

  it('says why nothing was suggested, and toasts a failure', async () => {
    getTopicSuggestions.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, topics: [] }),
    });
    await render({
      initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'custom', items: [] } },
    });
    await act(async () => button('agents.form.analytics.suggest')!.click());
    expect(container.querySelector('[role="status"]')!.textContent).toBe(
      'agents.form.analytics.suggestNone',
    );
    getTopicSuggestions.mockResolvedValue({ ok: false });
    await act(async () => button('agents.form.analytics.suggest')!.click());
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: {
          variant: 'destructive',
          message: 'agents.form.analytics.suggestFailed',
        },
      }),
    );
  });

  it('offers no suggestions before the agent is saved', async () => {
    await render({
      agentId: '',
      initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'custom', items: [] } },
    });
    expect(button('agents.form.analytics.suggest')).toBeUndefined();
    expect(button('agents.form.analytics.addTopic')).toBeDefined();
  });

  it('checks a new tag before adding it, and gives it an id', async () => {
    await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
    await act(async () => button('agents.form.analytics.addTag')!.click());
    const [name] = Array.from(dialog().querySelectorAll('input'));
    const description = dialog().querySelector('textarea')!;
    const submit = button('agents.form.analytics.modal.submitAddTag')!;
    await act(async () => submit.click());
    expect(dialog().textContent).toContain(
      'agents.form.analytics.errors.nameRequired',
    );
    expect(dialog().textContent).toContain(
      'agents.form.analytics.errors.descriptionRequired',
    );
    await act(async () => setValue(name, ' pricing QUESTION '));
    expect(dialog().textContent).toContain(
      'agents.form.analytics.errors.tagNameTaken',
    );
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

  it('keeps a tag id when it is renamed, so its history stays', async () => {
    await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
    await openMenu(0);
    await act(async () => menuItem('agents.form.analytics.edit').click());
    const name = dialog().querySelector('input')!;
    expect(name.value).toBe('Pricing question');
    await act(async () => setValue(name, 'Pricing'));
    await act(async () =>
      button('agents.form.analytics.modal.submitUpdateTag')!.click(),
    );
    expect(latest!.tags).toEqual([{ ...TAG, name: 'Pricing' }]);
  });

  it('confirms before removing a tag, since its history goes', async () => {
    await render({ initial: { ...DEFAULT_ANALYTICS, tags: [TAG] } });
    await openMenu(0);
    await act(async () => menuItem('agents.form.analytics.remove').click());
    expect(dialog().textContent).toContain(
      'agents.form.analytics.removeTag.title(Pricing question)',
    );
    expect(latest).toBeUndefined();
    await act(async () =>
      button('agents.form.analytics.removeTag.submit')!.click(),
    );
    expect(latest!.tags).toEqual([]);
  });

  it('removes a topic at once (re-adding the name restores it)', async () => {
    await render({
      initial: {
        ...DEFAULT_ANALYTICS,
        topics: {
          mode: 'custom',
          items: [
            { name: 'Installation', description: 'Pages such as: Docker' },
            { name: 'Billing', description: 'Pages such as: Plans' },
          ],
        },
      },
    });
    await openMenu(0);
    await act(async () => menuItem('agents.form.analytics.remove').click());
    expect(
      document.body.querySelector('[role="alertdialog"], [role="dialog"]'),
    ).toBeNull();
    expect(latest!.topics.items.map((item) => item.name)).toEqual(['Billing']);
  });

  it('rejects a topic description over the unit budget, counting CJK three times', async () => {
    await render({
      initial: { ...DEFAULT_ANALYTICS, topics: { mode: 'custom', items: [] } },
    });
    await act(async () => button('agents.form.analytics.addTopic')!.click());
    const name = dialog().querySelector('input')!;
    const description = dialog().querySelector('textarea')!;
    expect(description.value).toBe(
      'agents.form.analytics.modal.topicDescriptionStart ',
    );
    await act(async () => {
      setValue(name, '安装');
      setValue(description, '页'.repeat(51));
    });
    await act(async () =>
      button('agents.form.analytics.modal.submitAddTopic')!.click(),
    );
    expect(dialog().textContent).toContain(
      'agents.form.analytics.errors.topicDescriptionTooLong',
    );
    await act(async () => setValue(description, '页'.repeat(50)));
    await act(async () =>
      button('agents.form.analytics.modal.submitAddTopic')!.click(),
    );
    expect(latest!.topics.items).toEqual([
      { name: '安装', description: '页'.repeat(50) },
    ]);
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
    const section = container.querySelector(
      '[data-testid="analytics-section"]',
    )!;
    expect(section.querySelector('[role="note"]')!.textContent).toBe(
      'common.viewOnlyNotice',
    );
    expect(
      container.querySelector<HTMLButtonElement>(
        '[data-testid="analytics-enabled"]',
      )!.disabled,
    ).toBe(true);
    expect(modeItem('auto').disabled).toBe(true);
    expect(button('agents.form.analytics.addTag')).toBeUndefined();
    expect(button('agents.form.analytics.addTopic')).toBeUndefined();
    expect(container.querySelector('[aria-haspopup="menu"]')).toBeNull();
    expect(container.textContent).toContain('Pricing question');
  });

  it('shows what "From sources" will group by for a saved agent', async () => {
    getTopicSuggestions.mockResolvedValue(
      suggestions(['billing', 'data', 'integrations']),
    );
    await render();
    expect(getTopicSuggestions).toHaveBeenCalledWith('a1', 'token');
    const list = container.querySelector(
      '[data-testid="analytics-auto-topics"]',
    )!;
    expect(
      Array.from(list.querySelectorAll<HTMLElement>('[data-slot="badge"]')).map(
        (badge) => [badge.textContent, badge.dataset.variant],
      ),
    ).toEqual([
      ['billing', 'neutral'],
      ['data', 'neutral'],
      ['integrations', 'neutral'],
    ]);
    expect(list.textContent).toContain('agents.form.analytics.autoTopics');
    // Another mode hides it.
    await act(async () => modeItem('off').click());
    expect(
      container.querySelector('[data-testid="analytics-auto-topics"]'),
    ).toBeNull();
  });

  it('says when the sources give too few folders to group by', async () => {
    getTopicSuggestions.mockResolvedValue(suggestions(['billing']));
    await render();
    expect(container.textContent).toContain(
      'agents.form.analytics.autoTopicsNone',
    );
    expect(
      container.querySelector('[data-testid="analytics-auto-topics"]'),
    ).toBeNull();
  });

  it('asks for no preview before the agent is saved', async () => {
    await render({ agentId: '' });
    expect(getTopicSuggestions).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain(
      'agents.form.analytics.autoTopicsNone',
    );
  });

  it('puts Add tag beside the Tags title and the description as a hint line', async () => {
    await render();
    const tags = container.querySelector('[data-testid="analytics-tags"]')!;
    const header = tags.querySelector('[data-slot="section-header"]')!;
    expect(header.textContent).toContain('agents.form.analytics.addTag');
    expect(header.textContent).not.toContain(
      'agents.form.analytics.tagsDescription',
    );
    const hint = Array.from(tags.querySelectorAll('p')).find(
      (p) => p.textContent === 'agents.form.analytics.tagsDescription',
    )!;
    expect(hint.className).toContain('text-xs');
  });
});
