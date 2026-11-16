import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

import apiClient from '../api/client';
import PairDeviceModal from './PairDeviceModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const pairing = {
  device_code: 'dc_1',
  user_code: 'ABCD-1234',
  verification_uri: '',
  expires_in: 600,
  interval: 3,
};

describe('PairDeviceModal', () => {
  let container: HTMLDivElement;
  let root: Root;
  const setModalState = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('unexpected network request'))),
    );
    setModalState.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const clickButton = async (label: string) => {
    const button = Array.from(document.querySelectorAll('button')).find(
      (el) => el.textContent === label,
    );
    expect(button, `button ${label}`).toBeDefined();
    await act(async () => button!.click());
  };

  const startPairing = async () => {
    await act(async () => {
      root.render(
        <PairDeviceModal modalState="ACTIVE" setModalState={setModalState} />,
      );
    });
    await clickButton('settings.devices.pairing.start');
  };

  const alertText = () =>
    Array.from(document.querySelectorAll('[role="alert"]'))
      .map((el) => el.textContent)
      .join(' ');

  it('shows an error and stays on the form when the server cannot create a code', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false, error: 'redis_unavailable' }, 503),
    );
    const poll = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue(response({ ...pairing, status: 'pending' }));

    await startPairing();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(alertText()).toContain('common.actionFailed');
    expect(document.body.textContent).not.toContain(
      'settings.devices.pairing.waitingForCli',
    );
    expect(poll).not.toHaveBeenCalled();
  });

  it('shows the code and waits for the CLI once the pairing is created', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(response(pairing));

    await startPairing();

    expect(document.body.textContent).toContain(
      'settings.devices.pairing.waitingForCli',
    );
    expect(document.body.textContent).toContain('ABCD-1234');
    expect(alertText()).toBe('');
  });
});
