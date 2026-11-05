import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import activityService from './activityService';

afterEach(() => vi.restoreAllMocks());

describe('activityService.planned', () => {
  it("sends the viewer's time zone, which the server splits days in", async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ events: [] }),
    } as unknown as Response);
    await activityService.planned(
      new Date('2030-03-04T00:00:00Z'),
      new Date('2030-03-11T00:00:00Z'),
      't',
    );
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(get.mock.calls[0][0]).toContain(`tz=${encodeURIComponent(zone)}`);
  });
});
