import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import patService, { AccessTokenApiError } from './patService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

const TOKEN_ROW = {
  id: '7f1c2c1e-0f59-4d0a-9d55-0f6a3d1d7a11',
  name: 'ci',
  token_prefix: 'dgpt_pat_ab12cd',
  scopes: ['agents:read'],
  resource_filter: {},
  status: 'active',
  expires_at: null,
  last_used_at: null,
  last_used_ip: null,
  created_at: '2026-09-01T10:00:00+00:00',
  revoked_at: null,
};

describe('patService.list', () => {
  it('GETs /api/user/tokens with the session token and returns the body', async () => {
    const body = {
      success: true,
      tokens: [TOKEN_ROW],
      scopes: [{ name: 'agents:read', description: 'View agents' }],
      policy: { enabled: true },
    };
    const spy = vi.spyOn(apiClient, 'get').mockResolvedValue(response(body));

    const result = await patService.list('session-jwt');

    expect(spy).toHaveBeenCalledWith('/api/user/tokens', 'session-jwt');
    expect(result.tokens).toEqual([TOKEN_ROW]);
    expect(result.scopes[0].name).toBe('agents:read');
  });

  it('throws with the server message on a non-2xx response', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'Authentication required' }, 401),
    );

    await expect(patService.list(null)).rejects.toMatchObject({
      name: 'AccessTokenApiError',
      message: 'Authentication required',
      status: 401,
    });
  });
});

describe('patService.create', () => {
  it('POSTs the payload and returns the one-time plaintext token', async () => {
    const spy = vi.spyOn(apiClient, 'post').mockResolvedValue(
      response(
        {
          success: true,
          token: 'dgpt_pat_secret',
          personal_access_token: TOKEN_ROW,
        },
        201,
      ),
    );
    const payload = {
      name: 'ci',
      scopes: ['agents:read'],
      resource_filter: { agents: [TOKEN_ROW.id] },
      expires_in_days: 30,
    };

    const result = await patService.create(payload, 'session-jwt');

    expect(spy).toHaveBeenCalledWith(
      '/api/user/tokens',
      payload,
      'session-jwt',
    );
    expect(result.token).toBe('dgpt_pat_secret');
    expect(result.personal_access_token.id).toBe(TOKEN_ROW.id);
  });

  it.each([
    [400, 'Unknown scopes: nope:read'],
    [403, 'Personal access tokens are not available on this server'],
    [409, 'A token with this name already exists'],
  ])('surfaces the %i error message', async (status, message) => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false, message }, status),
    );

    const error = await patService
      .create({ name: 'ci', scopes: ['agents:read'] }, 'session-jwt')
      .catch((e) => e);

    expect(error).toBeInstanceOf(AccessTokenApiError);
    expect(error.message).toBe(message);
    expect(error.status).toBe(status);
  });

  it('throws an empty message when the error body is not JSON', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError('Unexpected token <');
      },
    } as unknown as Response);

    await expect(
      patService.create({ name: 'ci', scopes: ['agents:read'] }, null),
    ).rejects.toMatchObject({ message: '', status: 502 });
  });

  it('treats success:false on a 2xx as a failure', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false, message: 'nope' }, 200),
    );

    await expect(
      patService.create({ name: 'ci', scopes: ['agents:read'] }, null),
    ).rejects.toThrow('nope');
  });
});

describe('patService.revoke', () => {
  it('DELETEs the token by id', async () => {
    const spy = vi
      .spyOn(apiClient, 'delete')
      .mockResolvedValue(response({ success: true }));

    await expect(
      patService.revoke(TOKEN_ROW.id, 'session-jwt'),
    ).resolves.toEqual({ success: true });
    expect(spy).toHaveBeenCalledWith(
      `/api/user/tokens/${TOKEN_ROW.id}`,
      'session-jwt',
    );
  });

  it('throws when the token is not found', async () => {
    vi.spyOn(apiClient, 'delete').mockResolvedValue(
      response({ success: false, message: 'Token not found' }, 404),
    );

    await expect(patService.revoke('missing', null)).rejects.toThrow(
      'Token not found',
    );
  });
});
