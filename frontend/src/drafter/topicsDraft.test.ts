const client = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api/client', () => ({ default: client }));

import { getTopicsStatus } from './topicsDraft';

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

describe('getTopicsStatus', () => {
  beforeEach(() => client.get.mockReset());

  it('reads the status and why it is unavailable', async () => {
    client.get.mockResolvedValue(
      json({
        available: false,
        conversations: 0,
        needed: 10,
        reason: 'turned_off_for_this_agent',
      }),
    );
    await expect(getTopicsStatus('a1', 'tok')).resolves.toEqual({
      available: false,
      conversations: 0,
      needed: 10,
      reason: 'turned_off_for_this_agent',
    });
    expect(client.get.mock.calls[0][0]).toBe(
      '/api/drafter/topics/status?agent_id=a1',
    );
  });

  it('reads an older server without a reason as none', async () => {
    client.get.mockResolvedValue(
      json({ available: true, conversations: 12, needed: 10 }),
    );
    await expect(getTopicsStatus('a1', 'tok')).resolves.toMatchObject({
      available: true,
      reason: null,
    });
  });

  it.each([400, 401, 403, 404])(
    'is null when the suggestions are not for this caller (%i)',
    async (status) => {
      client.get.mockResolvedValue(json({ success: false }, status));
      await expect(getTopicsStatus('a1', 'tok')).resolves.toBeNull();
    },
  );

  it('fails on a server error or no answer, so the caller can retry', async () => {
    client.get.mockResolvedValue(json({ success: false }, 500));
    await expect(getTopicsStatus('a1', 'tok')).rejects.toThrow();
    client.get.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(getTopicsStatus('a1', 'tok')).rejects.toThrow();
    client.get.mockResolvedValue(json({ nonsense: true }));
    await expect(getTopicsStatus('a1', 'tok')).rejects.toThrow();
  });
});
