const get = vi.fn();
const post = vi.fn();
const del = vi.fn();

vi.mock('../client', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
    delete: (...args: unknown[]) => del(...args),
  },
}));

import customModelsService from './customModelsService';

const response = (body: unknown, status = 200) =>
  ({
    ok: status < 400,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
    json: () => Promise.resolve(body),
  }) as Response;

const PAYLOAD = {
  upstream_model_id: 'mistral-large',
  display_name: 'Mistral',
  base_url: 'https://api.mistral.ai/v1',
  api_key: 'sk-1',
  capabilities: {
    supports_tools: true,
    supports_structured_output: false,
    attachments: [],
    context_window: 128000,
  },
  enabled: true,
};

describe('customModelsService for a team', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    del.mockReset();
    get.mockResolvedValue(response([]));
    post.mockResolvedValue(response({ id: 'm1' }));
  });

  it("lists the caller's own models without an owner", async () => {
    await customModelsService.listCustomModels('tok');
    expect(get).toHaveBeenCalledWith('/api/user/models', 'tok', {});
  });

  it("lists a team's models for that team, whatever the current workspace", async () => {
    get.mockResolvedValue(response([{ id: 'm1', source: 'team' }]));
    const rows = await customModelsService.listCustomModels('tok', {
      owner: 'team',
      workspace: 'team-1',
    });
    expect(get).toHaveBeenCalledWith('/api/user/models?owner=team', 'tok', {
      'X-DocsGPT-Workspace': 'team-1',
    });
    expect(rows).toEqual([{ id: 'm1', source: 'team' }]);
  });

  it('adds a model for the team only when asked', async () => {
    await customModelsService.createCustomModel(
      { ...PAYLOAD, owner: 'team' },
      'tok',
    );
    expect(post).toHaveBeenLastCalledWith(
      '/api/user/models',
      { ...PAYLOAD, owner: 'team' },
      'tok',
    );
    await customModelsService.createCustomModel(PAYLOAD, 'tok');
    expect(post.mock.calls[1][1]).not.toHaveProperty('owner');
  });

  it("tests a model being added for the team as the team's", async () => {
    post.mockResolvedValue(response({ ok: true }));
    await customModelsService.testCustomModelPayload(
      {
        base_url: PAYLOAD.base_url,
        api_key: 'sk-1',
        upstream_model_id: 'mistral-large',
        owner: 'team',
      },
      'tok',
    );
    expect(post).toHaveBeenCalledWith(
      '/api/user/models/test',
      {
        base_url: PAYLOAD.base_url,
        api_key: 'sk-1',
        upstream_model_id: 'mistral-large',
        owner: 'team',
      },
      'tok',
    );
  });

  it('keeps the refusal code of a test the server turned down', async () => {
    post.mockResolvedValue(
      response(
        {
          success: false,
          error: 'workspace_role_required',
          message: "Only the team's Admins add models for it",
        },
        403,
      ),
    );
    const result = await customModelsService.testCustomModelPayload(
      {
        base_url: PAYLOAD.base_url,
        api_key: 'sk-1',
        upstream_model_id: 'mistral-large',
        owner: 'team',
      },
      'tok',
    );
    expect(result).toMatchObject({
      ok: false,
      code: 'workspace_role_required',
    });
    post.mockResolvedValue(
      response({ success: false, error: 'model_admin_required' }, 403),
    );
    expect(
      await customModelsService.testCustomModel('m1', 'tok'),
    ).toMatchObject({ ok: false, code: 'model_admin_required' });
  });

  it('copies a personal model into a team by id, naming the team in the body', async () => {
    post.mockResolvedValue(
      response({ id: 'm2', source: 'team', owner: 'team' }, 201),
    );
    const copied = await customModelsService.copyToTeam('m1', 'team-1', 'tok');
    expect(post).toHaveBeenCalledWith(
      '/api/user/models/m1/copy',
      { team_id: 'team-1' },
      'tok',
    );
    expect(copied).toMatchObject({ id: 'm2', owner: 'team' });
  });

  it("throws a refused copy with the server's body", async () => {
    post.mockResolvedValue(
      response(
        {
          success: false,
          error: 'model_already_in_team',
          model_id: 'm9',
          message: 'The team already has this model',
        },
        409,
      ),
    );
    await expect(
      customModelsService.copyToTeam('m1', 'team-1', 'tok'),
    ).rejects.toMatchObject({
      status: 409,
      payload: { error: 'model_already_in_team', model_id: 'm9' },
    });
  });

  it("gives back the team agents and workflows a deleted model's leaves behind", async () => {
    const usage = {
      agents: [{ id: 'a1', name: 'Support' }],
      workflows: [],
    };
    del.mockResolvedValue(response({ success: true, usage }));
    expect(await customModelsService.deleteCustomModel('m1', 'tok')).toEqual({
      success: true,
      usage,
    });
    del.mockResolvedValue(response({ success: true }));
    expect(await customModelsService.deleteCustomModel('m2', 'tok')).toEqual({
      success: true,
    });
  });
});
