import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import { readMcpAppResult, readMcpAppView } from './mcpAppsService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('readMcpAppView', () => {
  it.each([401, 403, 404])(
    'has no view to show on %i, so the chat shows the ordinary step',
    async (status) => {
      vi.spyOn(apiClient, 'post').mockResolvedValue(
        response({ success: false }, status),
      );
      expect(await readMcpAppView('row-1', 'ui://a', 't')).toBeNull();
    },
  );

  it.each([409, 502])(
    'fails on %i, so the view offers Retry',
    async (status) => {
      vi.spyOn(apiClient, 'post').mockResolvedValue(
        response({ success: false, error: 'nope' }, status),
      );
      await expect(readMcpAppView('row-1', 'ui://a', 't')).rejects.toThrow(
        'nope',
      );
    },
  );
});

describe('readMcpAppResult', () => {
  it('reads a saved call’s result by message and call', async () => {
    const result = { content: [], structuredContent: { k: 1 } };
    const post = vi
      .spyOn(apiClient, 'post')
      .mockResolvedValue(response({ success: true, result }));
    expect(await readMcpAppResult('m1', 'c1', 't')).toEqual(result);
    expect(post.mock.calls[0][1]).toEqual({ message_id: 'm1', call_id: 'c1' });
  });

  it('has nothing to read back on 404', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false }, 404),
    );
    expect(await readMcpAppResult('m1', 'c1', 't')).toBeNull();
  });
});
