import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({ revealSecret: vi.fn() }));
vi.mock('../api/services/monitorsService', () => ({ default: service }));

import MonitorLinkCard, {
  linkState,
  parseMonitorLink,
  type MonitorLink,
} from './MonitorLinkCard';
import monitorsReducer from './monitorsSlice';
import type { Monitor } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const URL = 'https://docs.example.com/api/triggers/trg_abc';
const APPROVE = 'https://docs.example.com/approve/apv_xyz';

describe('parseMonitorLink', () => {
  it('reads a webhook link from the tool result', () => {
    const result = JSON.stringify({
      monitor_id: 'm-1',
      url: URL,
      signature: 'github',
      secret: 'hidden from you',
    });
    expect(parseMonitorLink(result)).toEqual({
      kind: 'webhook',
      monitorId: 'm-1',
      url: URL,
      signature: 'github',
    });
  });

  it('reads a result cut short by truncation', () => {
    const result = `{"monitor_id": "m-1", "status": "active", "url": "${URL}", "method": "POST", "signature": "standard_webhooks", "example_curl": "body=...`;
    expect(parseMonitorLink(result)).toEqual({
      kind: 'webhook',
      monitorId: 'm-1',
      url: URL,
      signature: 'standard_webhooks',
    });
  });

  it('reads an approval link with its question and expiry', () => {
    expect(
      parseMonitorLink(
        JSON.stringify({
          monitor_id: 'm-2',
          url: APPROVE,
          question: 'Publish the post?',
          options: ['approve', 'reject'],
          expires_at: '2026-10-09T12:00:00+00:00',
        }),
      ),
    ).toEqual({
      kind: 'approval',
      monitorId: 'm-2',
      url: APPROVE,
      signature: 'none',
      question: 'Publish the post?',
      expiresAt: '2026-10-09T12:00:00+00:00',
    });
  });

  it('ignores other monitor results and errors', () => {
    expect(
      parseMonitorLink(
        JSON.stringify({
          monitor_id: 'm-1',
          url: 'https://example.com/status',
        }),
      ),
    ).toBeNull();
    expect(
      parseMonitorLink(JSON.stringify({ monitor_id: 'm-1', baseline: {} })),
    ).toBeNull();
    expect(parseMonitorLink('{"error": "nope"}')).toBeNull();
    expect(parseMonitorLink(undefined)).toBeNull();
  });
});

describe('MonitorLinkCard', () => {
  let container: HTMLDivElement;
  let root: Root;
  const makeStore = (monitors: Monitor[] = []) =>
    configureStore({
      reducer: {
        preference: () => ({ token: 'tok' }),
        monitors: monitorsReducer,
      },
      preloadedState: {
        monitors: {
          ...monitorsReducer(undefined, { type: 'init' }),
          loaded: true,
          byId: Object.fromEntries(monitors.map((m) => [m.monitor_id, m])),
          order: monitors.map((m) => m.monitor_id),
        },
      },
    });
  let store = makeStore();

  beforeEach(() => {
    service.revealSecret.mockReset();
    store = makeStore();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (signature: string, link: Partial<MonitorLink> = {}) => {
    await act(async () =>
      root.render(
        <Provider store={store}>
          <MonitorLinkCard
            link={{
              kind: 'webhook',
              monitorId: 'm-1',
              url: URL,
              signature,
              ...link,
            }}
          />
        </Provider>,
      ),
    );
  };
  const badge = () =>
    container.querySelector('[data-testid="monitor-link-state"]')?.textContent;

  const button = (label: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === label,
    );

  it('reveals the secret on request, and hides it again', async () => {
    service.revealSecret.mockResolvedValue({ state: 'ok', secret: 's3cret' });
    await render('github');
    expect(container.textContent).toContain(URL);
    expect(container.textContent).not.toContain('s3cret');
    await act(async () => button('monitors.linkCard.revealSecret')!.click());
    expect(service.revealSecret).toHaveBeenCalledWith('m-1', 'tok');
    expect(
      container.querySelector('[data-testid="monitor-link-secret"]')
        ?.textContent,
    ).toBe('s3cret');
    expect(container.textContent).toContain('monitors.linkCard.secretNote');
    await act(async () => button('monitors.linkCard.hideSecret')!.click());
    expect(container.textContent).not.toContain('s3cret');
  });

  it('says why a secret could not be shown', async () => {
    service.revealSecret.mockResolvedValue({ state: 'limited' });
    await render('hmac_sha256');
    await act(async () => button('monitors.linkCard.revealSecret')!.click());
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(
      'monitors.linkCard.revealLimited',
    );
  });

  it('offers no reveal for an unsigned link', async () => {
    await render('none');
    expect(button('monitors.linkCard.revealSecret')).toBeUndefined();
    expect(container.textContent).toContain(URL);
  });

  it('no longer offers the secret once the monitor has finished', async () => {
    store = makeStore([
      monitor({ status: 'completed', paused_reason: 'expired' }),
    ]);
    await render('github');
    expect(button('monitors.linkCard.revealSecret')).toBeUndefined();
    expect(badge()).toBe('monitors.linkCard.state.ended');
  });

  it('shows an approval link: question, copy, expiry and that it waits', async () => {
    await render('none', {
      kind: 'approval',
      monitorId: 'm-2',
      url: APPROVE,
      question: 'Publish the post?',
      expiresAt: '2999-10-09T12:00:00Z',
    });
    expect(container.textContent).toContain('monitors.linkCard.approvalTitle');
    expect(container.textContent).toContain('Publish the post?');
    expect(container.textContent).toContain(APPROVE);
    expect(container.textContent).toContain('monitors.linkCard.expires');
    expect(badge()).toBe('monitors.linkCard.state.pending');
    expect(button('monitors.linkCard.revealSecret')).toBeUndefined();
  });

  it('says when the approval was decided', async () => {
    store = makeStore([
      monitor({
        monitor_id: 'm-2',
        status: 'completed',
        paused_reason: 'decided',
      }),
    ]);
    await render('none', { kind: 'approval', monitorId: 'm-2', url: APPROVE });
    expect(badge()).toBe('monitors.linkCard.state.decided');
    expect(container.textContent).not.toContain('monitors.linkCard.expires');
  });
});

describe('linkState', () => {
  it('reads the monitor, or the expiry when the store lacks it', () => {
    const now = Date.parse('2026-10-06T12:00:00Z');
    expect(linkState('webhook', undefined, now)).toBe('active');
    expect(linkState('approval', undefined, now)).toBe('pending');
    expect(linkState('approval', undefined, now, '2026-10-06T11:00:00Z')).toBe(
      'ended',
    );
    expect(linkState('webhook', monitor({ status: 'paused' }), now)).toBe(
      'active',
    );
    expect(linkState('approval', monitor({ status: 'cancelled' }), now)).toBe(
      'ended',
    );
  });
});

function monitor(overrides: Partial<Monitor> = {}): Monitor {
  return {
    monitor_id: 'm-1',
    description: 'Deploy hook',
    status: 'active',
    source_type: 'webhook',
    watching: '',
    target: null,
    interval: null,
    interval_seconds: null,
    conversation_id: 'c1',
    agent_id: null,
    created_at: null,
    expires_at: null,
    next_check_at: null,
    last_checked_at: null,
    last_changed_at: null,
    last_woken_at: null,
    check_count: 0,
    wake_count: 0,
    max_wakes: 1,
    wakes_left: 1,
    last_error: null,
    paused_reason: null,
    approval_required: false,
    ...overrides,
  };
}
