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
