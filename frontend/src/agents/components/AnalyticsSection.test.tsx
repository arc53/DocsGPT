import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { AnalyticsConfig } from '../types';

vi.mock('react-redux', () => ({ useDispatch: () => vi.fn() }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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

function Harness({
  initial,
  available = true,
  disabled = false,
}: {
  initial?: AnalyticsConfig;
  available?: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState<AnalyticsConfig | undefined>(initial);
  return (
    <AnalyticsSection
      value={value}
      onChange={setValue}
      agentId="a1"
      available={available}
      maxTopics={3}
      maxTags={20}
      disabled={disabled}
      token="token"
    />
  );
}

describe('AnalyticsSection', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getTopicSuggestions.mockReset();
    getTopicSuggestions.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, topics: [] }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (props: React.ComponentProps<typeof Harness> = {}) =>
    act(async () => root.render(<Harness {...props} />));
  const toggle = () =>
    container.querySelector<HTMLButtonElement>(
      '[data-testid="analytics-toggle"]',
    )!;
  const section = () =>
    container.querySelector<HTMLElement>('[data-testid="analytics-section"]');
  const offBadge = () =>
    container.querySelector('[data-testid="analytics-off-badge"]');

  it('is titled Insights and holds the settings body', async () => {
    await render();
    expect(toggle().closest('h2')).not.toBeNull();
    // On is the default, so it shows no badge.
    expect(offBadge()).toBeNull();
    expect(toggle().textContent).toBe('agents.form.sections.analytics');
    await act(async () => toggle().click());
    expect(
      section()!.querySelector('[data-testid="analytics-topics"]'),
    ).not.toBeNull();
  });

  // FX-3: the topic folders load when the section opens, not on every
  // Overview load.
  it('fetches the topic folders only once it is opened', async () => {
    await render();
    expect(getTopicSuggestions).not.toHaveBeenCalled();
    await act(async () => toggle().click());
    expect(getTopicSuggestions).toHaveBeenCalledWith('a1', 'token');
  });

  it('marks an agent with insights off by a neutral Off badge beside the title', async () => {
    await render({ initial: { ...DEFAULT_ANALYTICS, enabled: false } });
    const badge = offBadge()!;
    expect(badge.textContent).toBe('agents.form.analytics.off');
    expect(badge.getAttribute('data-variant')).toBe('neutral');
    // Beside the heading, not inside the toggle.
    expect(toggle().contains(badge)).toBe(false);
    expect(badge.parentElement).toBe(toggle().closest('h2')!.parentElement);
  });

  it('is hidden while the server has labelling off and the agent has nothing set', async () => {
    await render({ available: false });
    expect(section()).toBeNull();
  });

  it('stays, with a note, for an agent with settings of its own', async () => {
    await render({
      available: false,
      initial: { ...DEFAULT_ANALYTICS, tags: [TAG] },
    });
    expect(section()!.querySelector('[role="note"]')!.textContent).toBe(
      'agents.form.analytics.serverOff',
    );
  });

  it('tells a read-only role it can only look', async () => {
    await render({ disabled: true });
    expect(section()!.querySelector('[role="note"]')!.textContent).toBe(
      'common.viewOnlyNotice',
    );
  });
});
