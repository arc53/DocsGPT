import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const service = vi.hoisted(() => ({ revealSecret: vi.fn() }));
vi.mock('../api/services/monitorsService', () => ({ default: service }));

import MonitorLinkCard, { parseMonitorLink } from './MonitorLinkCard';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const URL = 'https://docs.example.com/api/triggers/trg_abc';

describe('parseMonitorLink', () => {
  it('reads a webhook link from the tool result', () => {
    const result = JSON.stringify({
      monitor_id: 'm-1',
      url: URL,
      signature: 'github',
      secret: 'hidden from you',
    });
    expect(parseMonitorLink(result)).toEqual({
      monitorId: 'm-1',
      url: URL,
      signature: 'github',
    });
  });

  it('reads a result cut short by truncation', () => {
    const result = `{"monitor_id": "m-1", "status": "active", "url": "${URL}", "method": "POST", "signature": "standard_webhooks", "example_curl": "body=...`;
    expect(parseMonitorLink(result)).toEqual({
      monitorId: 'm-1',
      url: URL,
      signature: 'standard_webhooks',
    });
  });

  it('ignores other monitor results and errors', () => {
    expect(
      parseMonitorLink(
        JSON.stringify({
          monitor_id: 'm-1',
          url: 'https://docs.example.com/approve/apv_x',
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
  const store = configureStore({
    reducer: { preference: () => ({ token: 'tok' }) },
  });

  beforeEach(() => {
    service.revealSecret.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (signature: string) => {
    await act(async () =>
      root.render(
        <Provider store={store}>
          <MonitorLinkCard link={{ monitorId: 'm-1', url: URL, signature }} />
        </Provider>,
      ),
    );
  };

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
});
