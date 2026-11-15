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

import teamsService, {
  memberTeamRole,
  teamErrorMessage,
  teamRoleOf,
  TeamsApiError,
} from './teamsService';

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

  it('keeps a refusal code and its body', async () => {
    del.mockResolvedValue(
      response(409, {
        success: false,
        error: 'team_not_empty',
        message: 'Move or delete the team items first',
        counts: { agent: 2, folder: 1 },
      }),
    );
    const error = await teamsService.remove('team-1', 't').catch((e) => e);
    expect(error).toBeInstanceOf(TeamsApiError);
    expect(error.code).toBe('team_not_empty');
    expect(error.message).toBe('Move or delete the team items first');
    expect(error.body.counts).toEqual({ agent: 2, folder: 1 });
  });

  it('sends the new role names for members', async () => {
    post.mockResolvedValue(response(200, { success: true }));
    await teamsService.addMember(
      't1',
      { email: 'a@x.io', role: 'viewer' },
      't',
    );
    expect(post.mock.calls[0][1]).toEqual({ email: 'a@x.io', role: 'viewer' });
    put.mockResolvedValue(response(200, { success: true }));
    await teamsService.setMemberRole('t1', 'u1', 'editor', 't');
    expect(put.mock.calls[0][1]).toEqual({ role: 'editor' });
  });
});

describe('team roles and refusals', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    opts?.name ? `${key}(${opts.name})` : key;

  it('reads the new role first and maps the old names', () => {
    expect(memberTeamRole({ team_role: 'editor', role: 'team_member' })).toBe(
      'editor',
    );
    expect(memberTeamRole({ role: 'team_admin' })).toBe('admin');
    expect(memberTeamRole({ role: 'team_member' })).toBe('viewer');
    expect(teamRoleOf({ role: 'owner', member_role: 'team_admin' })).toBe(
      'owner',
    );
    expect(teamRoleOf({ member_role: 'team_admin' })).toBe('admin');
    expect(teamRoleOf({})).toBe('viewer');
  });

  it('maps each member refusal by its code', () => {
    const refusal = (code: string, message = 'server words') =>
      Object.assign(new TeamsApiError(409, message), { code });
    expect(teamErrorMessage(t, refusal('last_admin'), 'fallback')).toBe(
      'settings.teams.errors.lastAdmin',
    );
    expect(
      teamErrorMessage(t, refusal('owner_must_transfer'), 'fallback'),
    ).toBe('settings.teams.errors.ownerMustTransfer');
    expect(teamErrorMessage(t, refusal('owner_protected'), 'fallback')).toBe(
      'settings.teams.errors.ownerProtected',
    );
  });

  it("falls back to the server's message, then to the caller's", () => {
    expect(
      teamErrorMessage(t, new TeamsApiError(404, 'No such user'), 'fallback'),
    ).toBe('No such user');
    expect(teamErrorMessage(t, new Error('network'), 'fallback')).toBe(
      'fallback',
    );
  });
});
