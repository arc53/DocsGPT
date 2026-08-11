import { afterEach, describe, expect, it, vi } from 'vitest';

import userService from '../api/services/userService';
import { fetchMeRoles } from './useTokenAuth';

afterEach(() => vi.restoreAllMocks());

const okResponse = (roles: unknown) =>
  ({ ok: true, json: async () => ({ roles }) }) as unknown as Response;

describe('fetchMeRoles', () => {
  // Each test uses a distinct token so the module-level cache doesn't collide.

  it('dedupes concurrent calls for the same token', async () => {
    const spy = vi
      .spyOn(userService, 'getMe')
      .mockResolvedValue(okResponse(['user', 'admin']));
    const [a, b] = await Promise.all([
      fetchMeRoles('tok-dedupe'),
      fetchMeRoles('tok-dedupe'),
    ]);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(a).toEqual(['user', 'admin']);
    expect(b).toEqual(['user', 'admin']);
  });

  it('caches a successful result for the same token', async () => {
    const spy = vi
      .spyOn(userService, 'getMe')
      .mockResolvedValue(okResponse(['user']));
    expect(await fetchMeRoles('tok-cache')).toEqual(['user']);
    expect(await fetchMeRoles('tok-cache')).toEqual(['user']);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('returns null on failure and retries on the next call', async () => {
    const spy = vi
      .spyOn(userService, 'getMe')
      .mockResolvedValueOnce({ ok: false } as unknown as Response)
      .mockResolvedValueOnce(okResponse(['user']));
    expect(await fetchMeRoles('tok-retry')).toBeNull();
    expect(await fetchMeRoles('tok-retry')).toEqual(['user']);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it('returns null when getMe throws', async () => {
    vi.spyOn(userService, 'getMe').mockRejectedValue(new Error('network'));
    expect(await fetchMeRoles('tok-throw')).toBeNull();
  });

  it('defaults to [] when a successful response omits roles', async () => {
    vi.spyOn(userService, 'getMe').mockResolvedValue(okResponse(undefined));
    expect(await fetchMeRoles('tok-noroles')).toEqual([]);
  });
});
