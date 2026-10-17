import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'teams' in opts
        ? `${key}:${opts.teams}`
        : opts && 'count' in opts
          ? `${key}#${opts.count}`
          : key,
    i18n: { language: 'en' },
  }),
}));

import type { SponsorConfirmation } from '../sponsorConsent';
import SponsorConfirmModal from './SponsorConfirmModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const confirmation = (
  over: Partial<SponsorConfirmation['audience']> = {},
  mode?: SponsorConfirmation['mode'],
): SponsorConfirmation => ({
  ...(mode ? { mode } : {}),
  resources: [
    { key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' },
    { key: 'source:s1', type: 'source', id: 's1', name: null },
  ],
  audience: {
    teams: ['Support', 'Sales'],
    api_key: false,
    public_link: false,
    webhook: false,
    ...over,
  },
});

describe('SponsorConfirmModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    value: SponsorConfirmation | null,
    onConfirm = vi.fn(),
    onCancel = vi.fn(),
  ) => {
    await act(async () => {
      root.render(
        <SponsorConfirmModal
          confirmation={value}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />,
      );
    });
    return { onConfirm, onCancel };
  };

  const dialogText = () =>
    document.querySelector('[data-slot="modal-content"]')?.textContent ?? '';

  const button = (label: string) =>
    Array.from(document.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    ) as HTMLButtonElement;

  it('renders nothing without a pending confirmation', async () => {
    await render(null);
    expect(document.querySelector('[data-slot="modal-content"]')).toBeNull();
  });

  it('names each resource, with a fallback for an unnamed one', async () => {
    await render(confirmation());
    const text = dialogText();
    expect(text).toContain('agents.form.sponsorConfirm.title');
    expect(text).toContain('Jira');
    expect(text).toContain('agents.form.sponsorConfirm.types.tool');
    expect(text).toContain('agents.form.sponsors.unknownItem');
    expect(text).toContain('agents.form.sponsorConfirm.types.source');
  });

  it('lists the teams and only the outside entry points that are on', async () => {
    await render(confirmation({ public_link: true }));
    const text = dialogText();
    expect(text).toContain(
      'agents.form.sponsorConfirm.audienceTeams:Support and Sales',
    );
    expect(text).toContain('agents.form.sponsorConfirm.audiencePublicLink');
    expect(text).not.toContain('agents.form.sponsorConfirm.audienceApiKey');
    expect(text).not.toContain('agents.form.sponsorConfirm.audienceWebhook');
  });

  it('shows the API and webhook lines when the agent has them', async () => {
    await render(confirmation({ teams: [], api_key: true, webhook: true }));
    const text = dialogText();
    expect(text).not.toContain('audienceTeams');
    expect(text).toContain('agents.form.sponsorConfirm.audienceApiKey');
    expect(text).toContain('agents.form.sponsorConfirm.audienceWebhook');
  });

  it('says what adding does, counted, and ends on one muted stop line', async () => {
    await render(confirmation());
    const dialog = document.querySelector('[data-slot="modal-content"]')!;
    expect(dialog.textContent).toContain(
      'agents.form.sponsorConfirm.description#2',
    );
    expect(dialog.querySelector('[data-slot="alert"]')).toBeNull();
    const stop = Array.from(dialog.querySelectorAll('p')).find(
      (p) => p.textContent === 'agents.form.sponsorConfirm.stopNote#2',
    )!;
    expect(stop).toBeDefined();
    expect(stop.className).toContain('text-muted-foreground');
    expect(stop.className).toContain('text-xs');
    expect(button('agents.form.sponsorConfirm.confirm')).toBeDefined();
  });

  // Taking over an item already on the agent isn't adding it.
  it('asks to run an attached item, not to add it, in take-over mode', async () => {
    const one = confirmation({}, 'takeOver');
    one.resources = one.resources.slice(0, 1);
    const { onConfirm } = await render(one);
    const text = dialogText();
    expect(text).toContain('agents.form.sponsorConfirm.takeOverDescription#1');
    expect(text).not.toContain('agents.form.sponsorConfirm.description');
    expect(text).toContain('agents.form.sponsorConfirm.stopNote#1');
    expect(button('agents.form.sponsorConfirm.confirm')).toBeUndefined();
    await act(async () => {
      button('agents.form.sponsorConfirm.takeOverConfirm').click();
    });
    expect(onConfirm).toHaveBeenCalledWith(['tool:t1']);
  });

  it('confirms with every resource key', async () => {
    const { onConfirm, onCancel } = await render(confirmation());
    await act(async () => {
      button('agents.form.sponsorConfirm.confirm').click();
    });
    expect(onConfirm).toHaveBeenCalledWith(['tool:t1', 'source:s1']);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancels without confirming', async () => {
    const { onConfirm, onCancel } = await render(confirmation());
    await act(async () => {
      button('cancel').click();
    });
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
