import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import monitorsService from './monitorsService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('monitorsService approvals', () => {
  it('reads an approval without any session token', async () => {
    const get = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue(response({ question: 'Q', options: ['approve'] }));
    const result = await monitorsService.getApproval('apv_1');
    expect(result.state).toBe('ok');
    expect(get).toHaveBeenCalledWith('/api/approvals/apv_1', null);
  });

  it('maps a dead link to missing', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(response({}, 404));
    expect(await monitorsService.getApproval('apv_1')).toEqual({
      state: 'missing',
    });
  });

  it('sends the comment only when there is one', async () => {
    const post = vi
      .spyOn(apiClient, 'post')
      .mockResolvedValue(response({ decided: true, decision: 'approve' }));
    await monitorsService.decideApproval('apv_1', 'approve', '  ');
    expect(post).toHaveBeenLastCalledWith(
      '/api/approvals/apv_1',
      { decision: 'approve' },
      null,
    );
    await monitorsService.decideApproval('apv_1', 'approve', ' ok ');
    expect(post).toHaveBeenLastCalledWith(
      '/api/approvals/apv_1',
      { decision: 'approve', comment: 'ok' },
      null,
    );
  });

  it.each([
    [409, { error: 'already decided', decision: 'reject' }, 'already'],
    [404, { error: 'not found' }, 'missing'],
    [429, {}, 'limited'],
    [400, { error: 'bad' }, 'invalid'],
    [500, {}, 'error'],
  ])('maps %s to %s', async (status, body, state) => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(response(body, status));
    expect((await monitorsService.decideApproval('a', 'x', '')).state).toBe(
      state,
    );
  });
});

describe('monitorsService management', () => {
  it('lists one conversation', async () => {
    const get = vi
      .spyOn(apiClient, 'get')
      .mockResolvedValue(response({ monitors: [{ monitor_id: 'm1' }] }));
    expect(await monitorsService.list('t', 'c 1')).toEqual([
      { monitor_id: 'm1' },
    ]);
    expect(get).toHaveBeenCalledWith('/api/monitors?conversation_id=c%201', 't');
  });

  it('rejects a failed action with the server message', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ message: 'Monitor not found' }, 404),
    );
    await expect(monitorsService.act('m1', 'pause', 't')).rejects.toThrow(
      'Monitor not found',
    );
  });
});
