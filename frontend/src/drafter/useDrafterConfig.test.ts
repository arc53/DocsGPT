import { afterEach, describe, expect, it, vi } from 'vitest';

const getDrafterConfig = vi.hoisted(() => vi.fn());
vi.mock('./drafterApi', () => ({ getDrafterConfig }));

import { loadDrafterConfig, resetDrafterConfigCache } from './useDrafterConfig';

const ON = {
  enabled: true,
  model: { id: 'gpt-a', display_name: 'GPT A' },
  reason: null,
};
const NO_MODEL = { enabled: false, model: null, reason: 'no_model' };
const OFF = { enabled: false, model: null, reason: 'disabled' };
// What getDrafterConfig gives back when the request fails.
const UNREAD = { enabled: false, model: null, reason: 'unavailable' };

afterEach(() => {
  resetDrafterConfigCache();
  getDrafterConfig.mockReset();
});

describe('loadDrafterConfig', () => {
  it('reads once per token and shares a read in flight', async () => {
    getDrafterConfig.mockResolvedValue(ON);
    const [a, b] = await Promise.all([
      loadDrafterConfig('tok'),
      loadDrafterConfig('tok'),
    ]);
    expect(await loadDrafterConfig('tok')).toEqual(ON);
    expect(a).toEqual(ON);
    expect(b).toEqual(ON);
    expect(getDrafterConfig).toHaveBeenCalledTimes(1);
  });

  it('keeps an answer that there is no model, until the cache is reset', async () => {
    getDrafterConfig.mockResolvedValue(NO_MODEL);
    await loadDrafterConfig('tok');
    await loadDrafterConfig('tok');
    expect(getDrafterConfig).toHaveBeenCalledTimes(1);
    resetDrafterConfigCache();
    getDrafterConfig.mockResolvedValue(ON);
    expect(await loadDrafterConfig('tok')).toEqual(ON);
  });

  it('keeps an answer that the drafter is off on the server', async () => {
    getDrafterConfig.mockResolvedValue(OFF);
    await loadDrafterConfig('tok');
    await loadDrafterConfig('tok');
    expect(getDrafterConfig).toHaveBeenCalledTimes(1);
  });

  it('asks again after a read that failed', async () => {
    getDrafterConfig.mockResolvedValueOnce(UNREAD).mockResolvedValueOnce(ON);
    expect(await loadDrafterConfig('tok')).toEqual(UNREAD);
    expect(await loadDrafterConfig('tok')).toEqual(ON);
    expect(getDrafterConfig).toHaveBeenCalledTimes(2);
  });
});
