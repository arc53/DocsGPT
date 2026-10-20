import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { Agent } from '../types';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => vi.fn(),
}));

const service = vi.hoisted(() => ({
  updateAgent: vi.fn(),
  getTopicSuggestions: vi.fn(),
  getConfig: vi.fn(),
}));
vi.mock('../../api/services/userService', () => ({ default: service }));

import InsightsSettingsSheet from './InsightsSettingsSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const K = 'agents.form.analytics';

const TAG = {
  id: 'a1b2c3d4e5f60718',
  name: 'Pricing question',
  description: 'The user asks about prices.',
};

const classic = (analytics = { ...DEFAULT_ANALYTICS, tags: [TAG] }) =>
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
    service.getTopicSuggestions.mockReset();
    service.getTopicSuggestions.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          topics: [
            { name: 'billing', description: 'Pages such as: Plans' },
            { name: 'data', description: 'Pages such as: Export' },
          ],
        }),
    });
    service.getConfig.mockReset();
    service.getConfig.mockResolvedValue({
      json: () =>
        Promise.resolve({
          decision_analytics_enabled: true,
          analytics_max_topics: 15,
          analytics_max_tags: 3,
        }),
    });
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
    // The source folders: a classic agent groups by them.
    expect(panel().textContent).toContain('billing');
    expect(button(`${K}.customize`)).toBeDefined();
    expect(save().disabled).toBe(true);
    await act(async () => enabled().click());
    expect(save().disabled).toBe(false);
    await act(async () => enabled().click());
    expect(save().disabled).toBe(true);
  });

  it('takes the tag limit from the server', async () => {
    await render(
      classic({
        ...DEFAULT_ANALYTICS,
        tags: [
          TAG,
          { ...TAG, id: 'b2', name: 'B' },
          { ...TAG, id: 'c3', name: 'C' },
        ],
      }),
    );
    expect(button(`${K}.addTag`)).toBeUndefined();
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
      ...classic(),
      agent_type: 'workflow',
    } as Agent);
    expect(service.getTopicSuggestions).not.toHaveBeenCalled();
    expect(button(`${K}.customize`)).toBeUndefined();
    expect(panel().textContent).toContain(`${K}.topicHints.workflowOff`);
  });

  it('asks nothing of the server while closed', async () => {
    await render(classic(), { open: false });
    expect(service.getConfig).not.toHaveBeenCalled();
    expect(service.getTopicSuggestions).not.toHaveBeenCalled();
  });
});
