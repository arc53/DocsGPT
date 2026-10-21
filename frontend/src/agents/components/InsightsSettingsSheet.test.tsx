import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { Agent } from '../types';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// The server's switch and limits, as /api/config left them in the store.
const store = {
  preference: {
    token: 'token',
    analyticsEnabled: true,
    analyticsMaxTopics: 2,
    analyticsMaxOverlapping: 3,
  },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store),
  useDispatch: () => vi.fn(),
}));

const service = vi.hoisted(() => ({
  getAgent: vi.fn(),
  updateAgent: vi.fn(),
  getTopicFolders: vi.fn(),
  getConfig: vi.fn(),
}));
vi.mock('../../api/services/userService', () => ({ default: service }));

import InsightsSettingsSheet from './InsightsSettingsSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'agents.form.analytics';

const PRICING = {
  id: 'a1b2c3d4e5f60718',
  name: 'Pricing question',
  description: 'The user asks about prices.',
  overlap: true,
};

const classic = (analytics = { ...DEFAULT_ANALYTICS, topics: [PRICING] }) =>
  ({
    id: 'a1',
    name: 'Carrier FAQ',
    agent_type: 'classic',
    config: {
      guardrails: { enabled: true, controls: [] },
      api_write_allowlist: ['t1:write'],
      analytics,
    },
  }) as unknown as Agent;

describe('InsightsSettingsSheet', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.updateAgent.mockReset();
    service.updateAgent.mockResolvedValue({ ok: true });
    // The server's copy, read again just before a save: as loaded unless a
    // test says otherwise.
    service.getAgent.mockReset();
    service.getAgent.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(classic()) }),
    );
    service.getTopicFolders.mockReset();
    service.getTopicFolders.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          folders: [
            { name: 'billing', description: 'Pages such as: Plans' },
            { name: 'data', description: 'Pages such as: Export' },
          ],
        }),
    });
    service.getConfig.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (
    agent: Agent,
    props: { startEnabled?: boolean; open?: boolean } = {},
  ) => {
    const handlers = { onOpenChange: vi.fn(), onSaved: vi.fn() };
    await act(async () =>
      root.render(
        <InsightsSettingsSheet
          open={props.open ?? true}
          agent={agent}
          startEnabled={props.startEnabled}
          {...handlers}
        />,
      ),
    );
    await act(async () => undefined);
    return handlers;
  };

  const panel = () => document.body.querySelector('[role="dialog"]')!;
  const button = (name: string) =>
    Array.from(panel().querySelectorAll('button')).find(
      (b) => b.textContent === name,
    ) as HTMLButtonElement | undefined;
  const save = () => button('agents.form.buttons.save')!;
  const enabled = () =>
    panel().querySelector<HTMLButtonElement>(
      '[data-testid="analytics-enabled"]',
    )!;
  const sentConfig = () =>
    JSON.parse(
      (service.updateAgent.mock.calls[0][1] as FormData).get(
        'config',
      ) as string,
    );

  it('titles the panel and names the agent', async () => {
    await render(classic());
    expect(panel().querySelector('h2')!.textContent).toBe(
      'settings.analytics.insights.settings.title',
    );
    expect(panel().textContent).toContain('Carrier FAQ');
  });

  it('starts from the saved settings, with Save off until something changes', async () => {
    await render(classic());
    expect(panel().textContent).toContain('Pricing question');
    // The source folders: a classic agent's default topics.
    expect(panel().textContent).toContain('billing');
    expect(button(`${K}.addTopic`)).toBeDefined();
    expect(save().disabled).toBe(true);
    await act(async () => enabled().click());
    expect(save().disabled).toBe(false);
    await act(async () => enabled().click());
    expect(save().disabled).toBe(true);
  });

  describe('takes both topic limits from the server', () => {
    const own = (id: string, name: string, overlap: boolean) => ({
      ...PRICING,
      id: `${id}0000000`,
      name,
      overlap,
    });
    const two = [own('a1', 'A', false), own('b2', 'B', false)];

    it('offers Add topic while one kind has room', async () => {
      await render(
        classic({
          ...DEFAULT_ANALYTICS,
          topics: [...two, own('c3', 'C', true), own('d4', 'D', true)],
        }),
      );
      expect(button(`${K}.addTopic`)).toBeDefined();
    });

    it('drops it once both are full', async () => {
      await render(
        classic({
          ...DEFAULT_ANALYTICS,
          topics: [
            ...two,
            own('c3', 'C', true),
            own('d4', 'D', true),
            own('e5', 'E', true),
          ],
        }),
      );
      expect(button(`${K}.addTopic`)).toBeUndefined();
    });
  });

  it('saves only the insights on top of the saved config, then hands it back and closes', async () => {
    const agent = classic();
    const { onSaved, onOpenChange } = await render(agent);
    await act(async () => enabled().click());
    await act(async () => save().click());
    expect(service.updateAgent).toHaveBeenCalledTimes(1);
    expect(service.updateAgent.mock.calls[0][0]).toBe('a1');
    const form = service.updateAgent.mock.calls[0][1] as FormData;
    expect(Array.from(form.keys())).toEqual(['config']);
    const config = sentConfig();
    expect(config).toEqual({
      ...agent.config,
      analytics: { ...agent.config!.analytics, enabled: false },
    });
    expect(onSaved).toHaveBeenCalledWith(config);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('keeps the panel open with an Alert when the save fails', async () => {
    service.updateAgent.mockResolvedValue({ ok: false });
    const { onSaved, onOpenChange } = await render(classic());
    await act(async () => enabled().click());
    await act(async () => save().click());
    const alert = panel().querySelector('[role="alert"]')!;
    expect(alert.textContent).toContain(
      'settings.analytics.insights.settings.saveFailed',
    );
    expect(onSaved).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  // Another tab or editor changed the guardrails or the API write
  // allowlist since this page loaded: the insights save must not undo it.
  it('saves the insights on top of the config as the server has it now', async () => {
    const changed = {
      guardrails: { enabled: false, controls: [{ id: 'pii' }] },
      api_write_allowlist: [],
      analytics: { ...DEFAULT_ANALYTICS, topics: [PRICING] },
    };
    service.getAgent.mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ...classic(), config: changed }),
      }),
    );
    const { onSaved } = await render(classic());
    await act(async () => enabled().click());
    await act(async () => save().click());
    expect(service.getAgent).toHaveBeenCalledWith('a1', 'token');
    const config = sentConfig();
    expect(config).toEqual({
      ...changed,
      analytics: { ...changed.analytics, enabled: false },
    });
    expect(onSaved).toHaveBeenCalledWith(config);
  });

  it('saves nothing, with the Alert, when the fresh read fails', async () => {
    service.getAgent.mockResolvedValue({ ok: false });
    const { onSaved, onOpenChange } = await render(classic());
    await act(async () => enabled().click());
    await act(async () => save().click());
    expect(service.updateAgent).not.toHaveBeenCalled();
    expect(panel().querySelector('[role="alert"]')!.textContent).toContain(
      'settings.analytics.insights.settings.saveFailed',
    );
    expect(onSaved).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  describe('while a save is out', () => {
    let finish: (value: { ok: boolean }) => void;
    beforeEach(() => {
      service.updateAgent.mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
    });

    it('keeps the panel open: Cancel is off and Escape does nothing', async () => {
      const { onOpenChange, onSaved } = await render(classic());
      await act(async () => enabled().click());
      await act(async () => save().click());
      expect(button('agents.form.buttons.cancel')!.disabled).toBe(true);
      await act(async () => {
        document.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
        );
      });
      expect(onOpenChange).not.toHaveBeenCalled();
      await act(async () => finish({ ok: true }));
      expect(onSaved).toHaveBeenCalledTimes(1);
      expect(onOpenChange).toHaveBeenCalledTimes(1);
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it('lets Escape close it once no save is out', async () => {
      const { onOpenChange } = await render(classic());
      await act(async () => {
        document.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
        );
      });
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it('never closes a panel opened again after the one that saved', async () => {
      const agent = classic();
      const handlers = await render(agent);
      await act(async () => enabled().click());
      await act(async () => save().click());
      const show = (open: boolean) =>
        act(async () =>
          root.render(
            <InsightsSettingsSheet open={open} agent={agent} {...handlers} />,
          ),
        );
      // The page closes it and opens it again before the save answers.
      await show(false);
      await show(true);
      await act(async () => finish({ ok: true }));
      expect(handlers.onSaved).toHaveBeenCalledTimes(1);
      expect(handlers.onOpenChange).not.toHaveBeenCalled();
      expect(panel()).not.toBeNull();
    });
  });

  // IN-20: Turn on opens the panel already switched on, so the owner sees
  // what will run before saving.
  it('opened by Turn on, starts switched on and ready to save', async () => {
    const off = classic({ ...DEFAULT_ANALYTICS, enabled: false });
    const { onOpenChange } = await render(off, { startEnabled: true });
    expect(enabled().getAttribute('aria-checked')).toBe('true');
    expect(
      panel().querySelector('[data-testid="analytics-topics"]'),
    ).not.toBeNull();
    expect(save().disabled).toBe(false);
    // Cancel leaves the agent off.
    await act(async () => button('agents.form.buttons.cancel')!.click());
    expect(service.updateAgent).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('opened while off, shows only the switch', async () => {
    await render(classic({ ...DEFAULT_ANALYTICS, enabled: false }));
    expect(enabled().getAttribute('aria-checked')).toBe('false');
    expect(
      panel().querySelector('[data-testid="analytics-topics"]'),
    ).toBeNull();
    expect(save().disabled).toBe(true);
  });

  it('gives a workflow its own topic list only', async () => {
    await render({
      ...classic({ ...DEFAULT_ANALYTICS }),
      agent_type: 'workflow',
    } as Agent);
    expect(service.getTopicFolders).not.toHaveBeenCalled();
    expect(panel().textContent).toContain(`${K}.empty.workflow`);
  });

  it('asks nothing of the server while closed', async () => {
    await render(classic(), { open: false });
    expect(service.getConfig).not.toHaveBeenCalled();
    expect(service.getTopicFolders).not.toHaveBeenCalled();
  });
});
