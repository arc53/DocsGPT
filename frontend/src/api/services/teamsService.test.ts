const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const del = vi.fn();

vi.mock('../client', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    put: (...args: unknown[]) => put(...args),
    delete: (...args: unknown[]) => del(...args),
  },
}));

import teamsService, { TeamsApiError } from './teamsService';

const response = (status: number, body: unknown) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

describe('teamsService', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    put.mockReset();
    del.mockReset();
  });

  it('returns the parsed body on 2xx', async () => {
    get.mockResolvedValue(response(200, { success: true, teams: [] }));
    await expect(teamsService.list('t')).resolves.toEqual({
      success: true,
      teams: [],
    });
  });

  it('throws with the server message on 403', async () => {
    del.mockResolvedValue(
      response(403, { success: false, message: 'Only the owner can delete' }),
    );
    const error = await teamsService.remove('team-1', 't').catch((e) => e);
    expect(error).toBeInstanceOf(TeamsApiError);
    expect(error.status).toBe(403);
    expect(error.message).toBe('Only the owner can delete');
  });

  it('throws on a non-2xx with no JSON body', async () => {
    get.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new Error('not json')),
    });
    const error = await teamsService.list('t').catch((e) => e);
    expect(error).toBeInstanceOf(TeamsApiError);
    expect(error.status).toBe(500);
  });

  it('reads and writes resource settings', async () => {
    get.mockResolvedValue(response(200, { success: true, settings: [] }));
    await teamsService.getResourceSettings('agent', 'a 1', 't');
    expect(get.mock.calls[0][0]).toBe(
      '/api/resource_settings?resource_type=agent&resource_id=a%201',
    );
    put.mockResolvedValue(response(200, { success: true, settings: [] }));
    await teamsService.updateResourceSettings(
      'agent',
      'a1',
      { editors_can_share: true },
      't',
    );
    expect(put.mock.calls[0][0]).toBe('/api/resource_settings');
    expect(put.mock.calls[0][1]).toEqual({
      resource_type: 'agent',
      resource_id: 'a1',
      settings: { editors_can_share: true },
    });
  });
});
