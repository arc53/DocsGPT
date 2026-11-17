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

import de from '../../locale/de.json';
import en from '../../locale/en.json';
import es from '../../locale/es.json';
import fr from '../../locale/fr.json';
import jp from '../../locale/jp.json';
import ru from '../../locale/ru.json';
import zhTW from '../../locale/zh-TW.json';
import zh from '../../locale/zh.json';
import teamsService, {
  memberTeamRole,
  OUTSIDE_POLICIES,
  TEAM_ERROR_KEYS,
  teamErrorMessage,
  teamItemsRefusal,
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

  it('changes who may take the team items outside', async () => {
    put.mockResolvedValue(
      response(200, {
        success: true,
        changed: true,
        outside_policy: 'locked',
        can_set_outside_policy: true,
      }),
    );
    const body = await teamsService.setOutsidePolicy('t1', 'locked', 't');
    expect(put.mock.calls[0][0]).toBe('/api/teams/t1/outside_policy');
    expect(put.mock.calls[0][1]).toEqual({ policy: 'locked' });
    expect(body.outside_policy).toBe('locked');
  });

  it("refuses an Admin's unlock with its code", async () => {
    put.mockResolvedValue(
      response(403, {
        success: false,
        error: 'policy_owner_only',
        message: "Only the team's Owner can unlock it",
      }),
    );
    const error = await teamsService
      .setOutsidePolicy('t1', 'admins', 't')
      .catch((e) => e);
    expect(error).toBeInstanceOf(TeamsApiError);
    expect(error.code).toBe('policy_owner_only');
  });

  it('reads what the team takes outside', async () => {
    get.mockResolvedValue(
      response(200, {
        success: true,
        outside_policy: 'admins',
        can_set_outside_policy: false,
        shares: [],
        published: [],
      }),
    );
    const body = await teamsService.getOutside('t1', 't');
    expect(get.mock.calls[0][0]).toBe('/api/teams/t1/outside');
    expect(body.shares).toEqual([]);
  });

  it('shares a team item with the whole other team, at Viewer level', async () => {
    post.mockResolvedValue(
      response(201, { success: true, share: { id: 's1', created: true } }),
    );
    const body = await teamsService.shareTeamItem(
      't2',
      { resource_type: 'source', resource_id: 'src-1' },
      't',
    );
    expect(post.mock.calls[0][0]).toBe('/api/teams/t2/grants');
    expect(post.mock.calls[0][1]).toEqual({
      resource_type: 'source',
      resource_id: 'src-1',
      access_level: 'viewer',
    });
    expect(body.share.id).toBe('s1');
  });

  it('stops sharing a team item with a team, from either side', async () => {
    del.mockResolvedValue(response(200, { success: true, side: 'receiver' }));
    const body = await teamsService.unshareTeamItem(
      't2',
      { resource_type: 'tool', resource_id: 'tool 1' },
      't',
    );
    expect(del.mock.calls[0][0]).toBe(
      '/api/teams/t2/grants?resource_type=tool&resource_id=tool%201',
    );
    expect(body.side).toBe('receiver');
  });

  it('keeps the team items and the move offer of a uses_team_items refusal', async () => {
    const usesTeamItems = [
      {
        team_id: 't1',
        name: 'Operations',
        items: [{ key: 'source:s1', type: 'source', id: 's1', name: 'Docs' }],
      },
    ];
    post.mockResolvedValue(
      response(409, {
        success: false,
        error: 'uses_team_items',
        code: 'uses_team_items',
        message: 'words',
        uses_team_items: usesTeamItems,
        move_to: { team_id: 't1', name: 'Operations' },
      }),
    );
    const error = await teamsService
      .share('t2', { resource_type: 'agent', resource_id: 'a1' }, 't')
      .catch((e) => e);
    expect(teamItemsRefusal(error)).toEqual({
      usesTeamItems,
      moveTo: { team_id: 't1', name: 'Operations' },
      sharedWith: [],
    });
    expect(teamItemsRefusal(new Error('network'))).toBeNull();
    expect(
      teamItemsRefusal(new TeamsApiError(403, 'x', 'team_locked')),
    ).toBeNull();
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

  it('maps each refusal of taking items outside by its code', () => {
    const refusal = (code: string) =>
      new TeamsApiError(403, 'server words', code);
    const expected: Record<string, string> = {
      borrowed_resource: 'settings.teams.errors.borrowedResource',
      invalid_policy: 'settings.teams.errors.invalidPolicy',
      policy_owner_only: 'settings.teams.errors.policyOwnerOnly',
      team_item_shared_outside: 'settings.teams.errors.teamItemSharedOutside',
      team_locked: 'settings.teams.errors.teamLocked',
      team_share_not_member: 'settings.teams.errors.shareNotMember',
      team_share_same_team: 'settings.teams.errors.shareSameTeam',
      team_share_viewer_only: 'settings.teams.errors.shareViewerOnly',
      team_share_whole_team_only: 'settings.teams.errors.shareWholeTeamOnly',
      uses_team_items: 'settings.teams.errors.usesTeamItems',
      workspace_role_required: 'settings.teams.errors.roleRequired',
    };
    Object.entries(expected).forEach(([code, key]) =>
      expect(teamErrorMessage(t, refusal(code), 'fallback')).toBe(key),
    );
  });

  it('reads the code from a refusal a thunk serialized', () => {
    const serialized = {
      name: 'TeamsApiError',
      message: 'words',
      code: 'team_locked',
    };
    expect(teamErrorMessage(t, serialized, 'fallback')).toBe(
      'settings.teams.errors.teamLocked',
    );
  });

  it('has words for every code in all eight languages', () => {
    const locales = { de, en, es, fr, jp, ru, zh, zhTW };
    const read = (tree: object, path: string): unknown =>
      path
        .split('.')
        .reduce<unknown>(
          (node, part) => (node as Record<string, unknown> | undefined)?.[part],
          tree,
        );
    Object.entries(locales).forEach(([name, locale]) =>
      Object.values(TEAM_ERROR_KEYS).forEach((key) =>
        expect(typeof read(locale, key), `${name}: ${key}`).toBe('string'),
      ),
    );
  });

  it('lists the three outside policies in the order the setting shows them', () => {
    expect(OUTSIDE_POLICIES).toEqual(['admins', 'editors', 'locked']);
  });

  it("names the tools a team's account keeps inside the team", () => {
    const t = (key: string, opts?: Record<string, unknown>) =>
      opts?.tools ? `${key}(tools=${opts.tools})` : key;
    const body = {
      success: false,
      error: 'team_connection_outside',
      code: 'team_connection_outside',
      message: 'server words',
      tools: [
        { id: 'tl1', name: 'Create issue', connector_name: 'GitHub' },
        { id: 'tl2', name: 'Drive search', connector_name: 'Google Drive' },
      ],
    };
    const refusal = new TeamsApiError(
      409,
      'server words',
      'team_connection_outside',
      body,
    );
    expect(teamErrorMessage(t, refusal, 'fallback')).toBe(
      'settings.connectors.team.errors.teamConnectionOutsideNamed(tools=Create issue, Drive search)',
    );
    // A thunk's serialized refusal keeps the body too.
    expect(
      teamErrorMessage(
        t,
        {
          name: 'TeamsApiError',
          message: 'server words',
          code: 'team_connection_outside',
          body,
        },
        'fallback',
      ),
    ).toContain('teamConnectionOutsideNamed');
    // Without the tools it still says why, never the server's English.
    expect(
      teamErrorMessage(
        t,
        new TeamsApiError(409, 'server words', 'team_connection_outside'),
        'fallback',
      ),
    ).toBe('settings.connectors.team.errors.teamConnectionOutside');
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
