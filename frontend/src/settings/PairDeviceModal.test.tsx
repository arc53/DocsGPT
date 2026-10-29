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

  const advance = async (ms: number) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  };

  const expectExpiredForm = () => {
    expect(alertText()).toContain('settings.devices.pairing.expired');
    expect(document.body.textContent).not.toContain(
      'settings.devices.pairing.waitingForCli',
    );
    expect(document.body.textContent).not.toContain('ABCD-1234');
  };

  it('stops polling and asks for a new code once the code expires', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ ...pairing, expires_in: 30 }),
    );
    const poll = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue(response({ ...pairing, status: 'pending' }));

    await startPairing();
    await advance(27_000);
    expect(alertText()).toBe('');
    expect(poll).toHaveBeenCalledTimes(9);

    await advance(3000);
    expectExpiredForm();
    const pollsAtExpiry = poll.mock.calls.length;
    await advance(15_000);
    expect(poll).toHaveBeenCalledTimes(pollsAtExpiry);
  });

  it.each([
    [
      'no longer has the code',
      response({ success: false, error: 'pairing_not_found' }, 404),
    ],
    ['reports it expired', response({ ...pairing, status: 'expired' })],
    ['reports it cancelled', response({ ...pairing, status: 'cancelled' })],
  ])('treats the code as expired when the server %s', async (_case, reply) => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(response(pairing));
    const poll = vi.spyOn(apiClient, 'get').mockResolvedValue(reply);

    await startPairing();
    await advance(3000);

    expectExpiredForm();
    await advance(15_000);
    expect(poll).toHaveBeenCalledTimes(1);
  });

  it('polls at the interval the server asks for', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ ...pairing, interval: 5 }),
    );
    const poll = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue(response({ ...pairing, status: 'pending' }));

    await startPairing();
    await advance(4999);
    expect(poll).not.toHaveBeenCalled();
    await advance(1);
    expect(poll).toHaveBeenCalledTimes(1);
    await advance(5000);
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it('keeps waiting through a poll that fails for another reason', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(response(pairing));
    const poll = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValueOnce(
        response({ success: false, error: 'internal_error' }, 500),
      )
      .mockResolvedValue(response({ ...pairing, status: 'pending' }));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    await startPairing();
    await advance(6000);

    expect(poll).toHaveBeenCalledTimes(2);
    expect(alertText()).toBe('');
    expect(document.body.textContent).toContain('ABCD-1234');
  });

  it('generates a new code from the expired notice with the same details', async () => {
    const create = vi
      .spyOn(apiClient, 'post')
      .mockResolvedValueOnce(response(pairing))
      .mockResolvedValueOnce(
        response({ ...pairing, device_code: 'dc_2', user_code: 'WXYZ-9876' }),
      );
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, error: 'pairing_not_found' }, 404),
    );

    await startPairing();
    await advance(3000);
    expectExpiredForm();
    await clickButton('settings.devices.pairing.start');

    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[1][1]).toEqual(create.mock.calls[0][1]);
    expect(alertText()).toBe('');
    expect(document.body.textContent).toContain('WXYZ-9876');
  });

  it('ignores a poll that settles after the dialog closes', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(response(pairing));
    vi.spyOn(apiClient, 'delete').mockResolvedValue(
      response({ success: true }),
    );
    let settle!: (value: Response) => void;
    vi.spyOn(apiClient, 'get').mockReturnValue(
      new Promise<Response>((resolve) => {
        settle = resolve;
      }),
    );

    await startPairing();
    await advance(3000);
    await act(async () => {
      root.render(
        <PairDeviceModal modalState="INACTIVE" setModalState={setModalState} />,
      );
    });
    await act(async () => {
      settle(response({ success: false, error: 'pairing_not_found' }, 404));
    });
    await act(async () => {
      root.render(
        <PairDeviceModal modalState="ACTIVE" setModalState={setModalState} />,
      );
    });

    expect(alertText()).toBe('');
    expect(
      Array.from(document.querySelectorAll('button')).some(
        (el) => el.textContent === 'settings.devices.pairing.start',
      ),
    ).toBe(true);
  });
});
