import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import schedulesService from './schedulesService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('schedulesService.statsForAgent', () => {
  it('returns the stats body on success', async () => {
    const body = { days: 30, runs: 4, failed: 1, tokens: 120 };
    vi.spyOn(apiClient, 'get').mockResolvedValue(response(body));

    await expect(schedulesService.statsForAgent('a1', 't')).resolves.toEqual(
      body,
    );
  });

  it('rejects on an error response instead of returning its body as stats', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'Agent not found' }, 404),
    );

    await expect(schedulesService.statsForAgent('a1', 't')).rejects.toThrow();
  });
});

describe('schedulesService create and update errors', () => {
  it('rejects an update with the server message', async () => {
    vi.spyOn(apiClient, 'put').mockResolvedValue(
      response({ success: false, message: 'run_at is in the past.' }, 400),
    );

    await expect(
      schedulesService.update('s1', { run_at: '2020-01-01T00:00:00Z' }, 't'),
    ).rejects.toThrow('run_at is in the past.');
  });

  it('rejects a create with the server message', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response(
        { success: false, message: 'max schedules per user reached' },
        429,
      ),
    );

    await expect(
      schedulesService.create('a1', { instruction: 'x' }, 't'),
    ).rejects.toThrow('max schedules per user reached');
  });

  it('returns the saved schedule on success', async () => {
    vi.spyOn(apiClient, 'put').mockResolvedValue(
      response({ success: true, schedule: { id: 's1' } }),
    );

    await expect(
      schedulesService.update('s1', { instruction: 'x' }, 't'),
    ).resolves.toEqual({ success: true, schedule: { id: 's1' } });
  });
});
