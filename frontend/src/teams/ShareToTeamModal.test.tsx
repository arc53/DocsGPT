import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.account ? `${key}|${opts.account}` : key,
  }),
}));

vi.mock('../api/services/teamsService', () => ({
  default: {
    list: vi.fn().mockResolvedValue({
      teams: [{ id: 't1', name: 'Support', slug: 'support', owner_id: 'me' }],
    }),
    listResourceShares: vi.fn().mockResolvedValue({ shares: [] }),
    listMembers: vi.fn().mockResolvedValue({ members: [] }),
  },
}));

const setCredentialMode = vi.fn();
vi.mock('../api/services/connectorsService', () => ({
  default: {
    setCredentialMode: (...args: unknown[]) => setCredentialMode(...args),
  },
}));

import { prefSlice } from '../preferences/preferenceSlice';
import ShareToTeamModal, { type ShareCredentials } from './ShareToTeamModal';
import teamsReducer from './teamsSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const credentials = (
  overrides: Partial<ShareCredentials> = {},
): ShareCredentials => ({
  toolId: 'tool-1',
  connectorName: 'Linear',
  account: 'lena@meridian.example',
  mode: 'owner',
  hasWrites: false,
  ...overrides,
});

describe('ShareToTeamModal credentials', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    setCredentialMode.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (creds?: ShareCredentials) => {
    const store = configureStore({
      reducer: { preference: prefSlice.reducer, teams: teamsReducer },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <ShareToTeamModal
            resourceType="tool"
            resourceId="tool-1"
            resourceName="Linear"
            credentials={creds}
            onClose={() => undefined}
          />
        </Provider>,
      );
    });
  };

  // A compact segmented choice, not a pair of picker tiles.
  const toggle = (value: 'owner' | 'member') =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find(
      (item) =>
        item.textContent === `settings.connectors.sharing.${value}Short`,
    )!;
  const picker = () =>
    document.body.querySelector<HTMLButtonElement>('[role="combobox"]')!;

  it('shows nothing about accounts for a resource without a connection', async () => {
    await render();
    expect(document.body.textContent).not.toContain(
      'settings.connectors.share.heading',
    );
  });

  it('says whose account members use on a tool that only reads', async () => {
    await render(credentials());
    expect(document.body.querySelector('[role="note"]')).toBeNull();
    expect(document.body.querySelector('[data-slot="option-card"]')).toBeNull();
    expect(toggle('owner').getAttribute('aria-checked')).toBe('true');
    expect(document.body.textContent).toContain(
      'settings.connectors.share.ownerWarning|lena@meridian.example',
    );
  });

  it('asks only for the confirmation on a tool that can act, with no warning box', async () => {
    await render(credentials({ hasWrites: true }));
    expect(document.body.querySelector('[role="note"]')).toBeNull();
    expect(document.body.textContent).not.toContain(
      'settings.connectors.share.ownerWarning',
    );
    expect(document.body.querySelector('#share-confirm-writes')).not.toBeNull();
  });

  it('blocks sharing an owner-mode tool with writes until confirmed', async () => {
    await render(credentials({ hasWrites: true }));
    expect(picker().disabled).toBe(true);
    const box = document.body.querySelector<HTMLButtonElement>(
      '#share-confirm-writes',
    )!;
    await act(async () => box.click());
    expect(picker().disabled).toBe(false);
  });

  it('saves a mode change and rolls back when the save fails', async () => {
    setCredentialMode.mockResolvedValue({ success: false });
    await render(credentials({ hasWrites: true }));
    await act(async () => toggle('member').click());
    expect(setCredentialMode).toHaveBeenCalledWith('tool-1', 'member', null);
    expect(toggle('owner').getAttribute('aria-checked')).toBe('true');
    expect(document.body.textContent).toContain(
      'settings.connectors.share.saveFailed',
    );
  });

  it('locks the other mode when an admin forces one', async () => {
    await render(credentials({ forcedMode: 'member' }));
    expect(toggle('member').getAttribute('aria-checked')).toBe('true');
    expect(toggle('owner').disabled).toBe(true);
    expect(document.body.textContent).toContain(
      'settings.connectors.share.forced',
    );
  });
});
