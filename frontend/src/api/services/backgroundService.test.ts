import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
}));
vi.mock('../client', () => ({
  default: client,
  baseURL: 'https://api.example.com',
}));

import backgroundService, { BACKGROUND_PATHS } from './backgroundService';

const ok = (body: unknown) => ({
  ok: true,
  status: 200,
  json: async () => body,
});

describe('backgroundService', () => {
  const fetchMock = vi.fn(async () => ({ ok: true }));
  const beacon = vi.fn(() => true);

  beforeEach(() => {
    Object.values(client).forEach((fn) => fn.mockReset());
    fetchMock.mockClear();
    beacon.mockClear();
    vi.stubGlobal('fetch', fetchMock);
    Object.defineProperty(navigator, 'sendBeacon', {
      value: beacon,
      configurable: true,
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (navigator as unknown as Record<string, unknown>).sendBeacon;
  });

  it('builds the job and presence paths', () => {
    expect(BACKGROUND_PATHS.JOBS('c 1')).toBe(
      '/api/background_jobs?conversation_id=c%201',
    );
    expect(BACKGROUND_PATHS.JOB_CANCEL('j1')).toBe(
      '/api/background_jobs/j1/cancel',
    );
    expect(BACKGROUND_PATHS.CONVERSATION_READ('c1')).toBe(
      '/api/conversations/c1/read',
    );
  });

  it('lists a conversation’s jobs', async () => {
    client.get.mockResolvedValue(ok({ jobs: [{ job_id: 'j1' }] }));
    expect(await backgroundService.listJobs('c1', 'tok')).toEqual([
      { job_id: 'j1' },
    ]);
    expect(client.get).toHaveBeenCalledWith(
      '/api/background_jobs?conversation_id=c1',
      'tok',
    );
  });

  it('throws on an error status', async () => {
    client.get.mockResolvedValue({ ok: false, status: 404 });
    await expect(backgroundService.getJob('j1', 'tok')).rejects.toThrow(
      'HTTP 404',
    );
  });

  describe('reportPresence', () => {
    const report = {
      tab_id: 'tab-1',
      conversation_id: 'c1',
      visible: true,
    };

    it('posts a report with the token', () => {
      backgroundService.reportPresence(report, 'tok');
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.example.com/api/presence',
        expect.objectContaining({
          method: 'POST',
          keepalive: false,
          headers: expect.objectContaining({ Authorization: 'Bearer tok' }),
        }),
      );
      expect(beacon).not.toHaveBeenCalled();
    });

    it('a closing report with a token rides keepalive (a beacon has no headers)', () => {
      backgroundService.reportPresence({ ...report, closing: true }, 'tok');
      expect(beacon).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.example.com/api/presence',
        expect.objectContaining({ keepalive: true }),
      );
    });

    it('a closing report without auth goes as a beacon', () => {
      backgroundService.reportPresence({ ...report, closing: true }, null);
      expect(beacon).toHaveBeenCalledWith(
        'https://api.example.com/api/presence',
        expect.any(Blob),
      );
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('falls back to fetch when the beacon is refused', () => {
      beacon.mockReturnValueOnce(false);
      backgroundService.reportPresence({ ...report, closing: true }, null);
      expect(fetchMock).toHaveBeenCalled();
    });

    it('never throws', () => {
      fetchMock.mockImplementationOnce(() => {
        throw new Error('offline');
      });
      expect(() =>
        backgroundService.reportPresence(report, 'tok'),
      ).not.toThrow();
    });
  });

  it('forgets a subscription on exit with a keepalive DELETE', () => {
    backgroundService.forgetPushSubscriptionOnExit('https://push/x', 'tok');
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/api/push/subscriptions',
      expect.objectContaining({
        method: 'DELETE',
        keepalive: true,
        body: JSON.stringify({ endpoint: 'https://push/x' }),
      }),
    );
  });

  it('saves and deletes a subscription through the API client', async () => {
    client.post.mockResolvedValue(ok({ success: true }));
    client.delete.mockResolvedValue(ok({ success: true }));
    await backgroundService.savePushSubscription(
      { endpoint: 'https://push/x' },
      'tok',
    );
    await backgroundService.deletePushSubscription('https://push/x', 'tok');
    expect(client.post).toHaveBeenCalledWith(
      '/api/push/subscriptions',
      { endpoint: 'https://push/x' },
      'tok',
    );
    expect(client.delete).toHaveBeenCalledWith(
      '/api/push/subscriptions',
      'tok',
      {
        endpoint: 'https://push/x',
      },
    );
  });
});
