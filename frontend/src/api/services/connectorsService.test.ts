const get = vi.fn();
const post = vi.fn();
const throttledGet = vi.fn();

vi.mock('../client', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
  throttledApiClient: {
    get: (...args: unknown[]) => throttledGet(...args),
  },
}));

import endpoints from '../endpoints';
import connectorsService from './connectorsService';

const response = (body: unknown) =>
  ({ ok: true, status: 200, json: () => Promise.resolve(body) }) as Response;

describe('connectorsService for a team', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    throttledGet.mockReset();
    throttledGet.mockResolvedValue(response({ success: true }));
    post.mockResolvedValue(response({ success: true }));
  });

  it("lists the caller's own connections without an owner", async () => {
    await connectorsService.listConnections('tok');
    expect(throttledGet).toHaveBeenCalledWith('/api/connections', 'tok', {});
  });

  it("lists a team's connections for that team, whatever the current workspace", async () => {
    await connectorsService.listConnections('tok', {
      owner: 'team',
      workspace: 'team-1',
    });
    expect(throttledGet).toHaveBeenCalledWith(
      '/api/connections?owner=team',
      'tok',
      { 'X-DocsGPT-Workspace': 'team-1' },
    );
  });

  it("reads the team's catalog states with owner=team", async () => {
    await connectorsService.getCatalog('tok', {
      owner: 'team',
      workspace: 'team-1',
    });
    expect(throttledGet).toHaveBeenCalledWith(
      '/api/connectors/catalog?owner=team',
      'tok',
      { 'X-DocsGPT-Workspace': 'team-1' },
    );
  });

  it('connects pasted credentials for the team only when asked', async () => {
    await connectorsService.createConnection(
      { connector_key: 'brave', credentials: { api_key: 'k' } },
      'tok',
    );
    expect(post.mock.calls[0][1]).not.toHaveProperty('owner');
    await connectorsService.createConnection(
      { connector_key: 'brave', credentials: { api_key: 'k' }, owner: 'team' },
      'tok',
    );
    expect(post.mock.calls[1][0]).toBe('/api/connections');
    expect(post.mock.calls[1][1]).toMatchObject({ owner: 'team' });
  });

  it("adds a team tool that runs on each person's own account", async () => {
    post.mockResolvedValue(response({ success: true, id: 'tool-1' }));
    await expect(
      connectorsService.createMemberTool(
        { connector_key: 'github', folder_id: 'f1' },
        'tok',
      ),
    ).resolves.toEqual({ success: true, id: 'tool-1' });
    expect(post).toHaveBeenCalledWith(
      '/api/tools/member',
      { connector_key: 'github', folder_id: 'f1' },
      'tok',
    );
  });

  it('passes a refusal body through for the error map', async () => {
    post.mockResolvedValue({
      ok: false,
      status: 409,
      json: () =>
        Promise.resolve({
          success: false,
          error: 'connect_personal_first',
          connector_key: 'github',
        }),
    } as Response);
    await expect(
      connectorsService.createMemberTool({ connector_key: 'github' }, 'tok'),
    ).resolves.toMatchObject({ error: 'connect_personal_first' });
  });

  it('returns whether a Reconnect replaces the account', async () => {
    post.mockResolvedValue(
      response({
        success: true,
        kind: 'oauth',
        replace: true,
        authorization_url: 'https://x',
        state: 's',
      }),
    );
    const result = await connectorsService.reconnect('c1', {}, 'tok');
    expect(result.success && result.kind === 'oauth' && result.replace).toBe(
      true,
    );
  });
});

describe('connector endpoints for a team', () => {
  it('asks the sign-in for the team only with owner=team', () => {
    expect(endpoints.USER.CONNECTOR_AUTH('google_drive')).toBe(
      '/api/connectors/auth?provider=google_drive',
    );
    expect(
      endpoints.USER.CONNECTOR_AUTH('google_drive', undefined, false, 'team'),
    ).toBe('/api/connectors/auth?provider=google_drive&owner=team');
    expect(
      endpoints.USER.CONNECTOR_AUTH('github', 'c1', true, 'personal'),
    ).toBe('/api/connectors/auth?provider=github&connection_id=c1&install=1');
  });
});
