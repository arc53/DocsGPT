import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_ANALYTICS } from '../analyticsConfig';
import type { AnalyticsConfig } from '../types';

vi.mock('react-redux', () => ({ useDispatch: () => vi.fn() }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const getTopicFolders = vi.fn();
vi.mock('../../api/services/userService', () => ({
  default: {
    getTopicFolders: (...args: unknown[]) => getTopicFolders(...args),
  },
}));

import AnalyticsSection from './AnalyticsSection';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const PRICING = {
  id: 'a1b2c3d4e5f60718',
  name: 'Pricing question',
  description: 'The user asks about prices.',
  overlap: true,
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
      maxOverlapping={20}
      disabled={disabled}
      token="token"
    />
  );
}

describe('AnalyticsSection', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getTopicFolders.mockReset();
    getTopicFolders.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ success: true, folders: [] }),
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
    expect(getTopicFolders).not.toHaveBeenCalled();
    await act(async () => toggle().click());
    expect(getTopicFolders).toHaveBeenCalledWith('a1', 'token');
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
      initial: { ...DEFAULT_ANALYTICS, topics: [PRICING] },
    });
    expect(section()!.querySelector('[role="note"]')!.textContent).toBe(
      'agents.form.analytics.serverOff',
    );
  });

  // The folders don't hang on the server's switch: with it off, an agent's
  // hidden folders still show, and can be shown again.
  it('loads the folders with the server switch off, so hidden ones can come back', async () => {
    getTopicFolders.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          success: true,
          folders: [{ name: 'Billing', description: 'Pages such as: Plans' }],
        }),
    });
    await render({
      available: false,
      initial: { ...DEFAULT_ANALYTICS, hidden_folders: ['Billing'] },
    });
    await act(async () => toggle().click());
    await act(async () => undefined);
    expect(getTopicFolders).toHaveBeenCalledWith('a1', 'token');
    const show = Array.from(section()!.querySelectorAll('button')).find(
      (button) =>
        button.textContent === 'agents.form.analytics.notes.show' ||
        button.textContent === 'agents.form.analytics.empty.showFolders',
    );
    expect(show).toBeDefined();
    expect(section()!.textContent).not.toContain(
      'agents.form.analytics.empty.noFolders',
    );
  });

  it('tells a read-only role it can only look', async () => {
    await render({ disabled: true });
    expect(section()!.querySelector('[role="note"]')!.textContent).toBe(
      'common.viewOnlyNotice',
    );
  });
});
